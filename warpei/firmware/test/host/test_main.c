/* Host unit tests for the portable firmware logic. Build and run:
 *     cd firmware/test/host && make test
 * No ESP-IDF needed. Each test is a function; a failed CHECK prints the
 * line and the run exits non-zero at the end. */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "wp_frame.h"
#include "mlx90614.h"
#include "emc2101.h"
#include "buttons.h"
#include "thermal_logic.h"
#include "control_logic.h"

static int failures = 0, checks = 0;
#define CHECK(cond) do { checks++; if (!(cond)) { failures++; printf("  FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); } } while (0)
#define TEST(name) static void name(void); static void name##_run(void) { printf("%s\n", #name); name(); } static void name(void)

/* ---------------------------------------------------------------- CRC and framing */

TEST(crc8_matches_python_and_examples)
{
    CHECK(wp_crc8((const uint8_t *)"123456789", 9) == 0xF4);
    uint8_t out[WP_MAX_FRAME];
    size_t n = wp_encode(WP_MSG_CAL_START, NULL, 0, out, sizeof out);
    CHECK(n == 4 && out[0] == 0xA5 && out[1] == 0x10 && out[2] == 0x00 && out[3] == 0x57);
    uint8_t flip = 1;
    n = wp_encode(WP_MSG_FLIP, &flip, 1, out, sizeof out);
    CHECK(n == 5 && out[4] == 0x66);
    uint8_t st = WP_FW_STATE_ON;
    n = wp_encode(WP_MSG_HEARTBEAT, &st, 1, out, sizeof out);
    CHECK(n == 5 && out[4] == 0x70);
    CHECK(wp_encode(1, out, 33, out, sizeof out) == 0);          /* too long */
}

TEST(pack_unpack_round_trip_with_sign_extension)
{
    int32_t in[4] = { -123, 250, 50, 1500 };   /* TEMPERATURE: i16 i16 u8 u16 */
    uint8_t payload[WP_MAX_PAYLOAD];
    uint8_t len = wp_pack(WP_MSG_TEMPERATURE, in, 4, payload);
    CHECK(len == WP_LEN_TEMPERATURE && len == 7);
    int32_t outf[4] = {0};
    CHECK(wp_unpack(WP_MSG_TEMPERATURE, payload, len, outf, 4) == 7);
    CHECK(outf[0] == -123 && outf[1] == 250 && outf[2] == 50 && outf[3] == 1500);
    CHECK(wp_pack(WP_MSG_TEMPERATURE, in, 3, payload) == 0);     /* wrong field count */
    CHECK(wp_unpack(0x55, payload, 7, outf, 4) == 0);              /* unknown id */
    CHECK(wp_unpack(WP_MSG_TEMPERATURE, payload, 6, outf, 4) == 0);/* wrong length */
}

TEST(decoder_ten_thousand_frames_random_chunks)
{
    wp_decoder_t d; wp_decoder_init(&d);
    wp_message_t m;
    srand(7);
    int got = 0;
    for (int i = 0; i < 10000; i++) {
        int32_t f[4] = { (rand() % 601) - 300, 250, 50, 1500 };
        uint8_t payload[8], frame[WP_MAX_FRAME];
        uint8_t len = wp_pack(WP_MSG_TEMPERATURE, f, 4, payload);
        size_t n = wp_encode(WP_MSG_TEMPERATURE, payload, len, frame, sizeof frame);
        for (size_t b = 0; b < n; b++) {
            if (wp_decoder_feed(&d, frame[b], &m)) {
                int32_t out[4];
                wp_unpack(m.id, m.payload, m.len, out, 4);
                if (out[0] == f[0]) got++;
            }
        }
    }
    CHECK(got == 10000 && d.crc_errors == 0 && d.frames == 10000);
}

TEST(decoder_drops_corrupt_and_recovers)
{
    wp_decoder_t d; wp_decoder_init(&d);
    wp_message_t m;
    int delivered = 0;
    for (int i = 0; i < 1000; i++) {
        uint8_t cmd = WP_BUTTON_COMMAND_FLIP_SHORT, frame[8];
        size_t n = wp_encode(WP_MSG_BUTTON, &cmd, 1, frame, sizeof frame);
        if (i % 100 == 50) frame[n - 1] ^= 0xFF;
        for (size_t b = 0; b < n; b++) if (wp_decoder_feed(&d, frame[b], &m)) delivered++;
    }
    CHECK(delivered == 990 && d.crc_errors == 10);
    /* garbage with a false start byte and a bad length, then a good frame */
    uint8_t junk[] = { 0x00, 0xA5, 0xFF, 0x7F, 0x01, 0x02 };
    for (size_t b = 0; b < sizeof junk; b++) CHECK(!wp_decoder_feed(&d, junk[b], &m));
    uint8_t good[8]; size_t n = wp_encode(WP_MSG_CAL_START, NULL, 0, good, sizeof good);
    bool ok = false;
    for (size_t b = 0; b < n; b++) ok = wp_decoder_feed(&d, good[b], &m) || ok;
    CHECK(ok && m.id == WP_MSG_CAL_START && d.bad_length == 1);
}

/* ---------------------------------------------------------------- MLX90614 */

typedef struct { uint16_t value; int fail; int corrupt_pec; int calls; uint8_t last_cmd; } fake_bus_t;

static int fake_xfer(void *ctx, uint8_t addr, const uint8_t *w, size_t wlen, uint8_t *r, size_t rlen, uint32_t to)
{
    (void)to;
    fake_bus_t *b = ctx; b->calls++;
    if (b->fail) return -1;
    if (wlen != 1 || rlen != 3) return -1;
    b->last_cmd = w[0];
    r[0] = (uint8_t)(b->value & 0xFF); r[1] = (uint8_t)(b->value >> 8);
    uint8_t covered[5] = { (uint8_t)(addr << 1), w[0], (uint8_t)((addr << 1) | 1), r[0], r[1] };
    r[2] = mlx90614_pec(covered, 5) ^ (b->corrupt_pec ? 0x5A : 0);
    return 0;
}

TEST(mlx90614_conversion_and_pec)
{
    /* Datasheet: raw 0x3AF3 (15091) -> 301.82 K = 28.67 C */
    CHECK(mlx90614_raw_to_c_x10(0x3AF3) == 287);
    CHECK(mlx90614_raw_to_c_x10(13658) == 0);       /* 273.16 K -> 0.0 C */
    CHECK(mlx90614_raw_to_c_x10(0x27AD) == -700);   /* -70 C lower limit */
    uint8_t v[5] = { 0xB4, 0x07, 0xB5, 0xF3, 0x3A };
    CHECK(mlx90614_pec(v, 5) == wp_crc8(v, 5));     /* same CRC as the link */
}

TEST(mlx90614_reads_and_rejects)
{
    fake_bus_t bus = { .value = 0x3AF3 };
    mlx90614_t dev;
    CHECK(mlx90614_init(&dev, fake_xfer, &bus, 0, 0) == MLX_OK && dev.addr == 0x5A);
    int16_t t = 0;
    CHECK(mlx90614_read_object_c_x10(&dev, &t) == MLX_OK && t == 287 && bus.last_cmd == MLX90614_RAM_TOBJ1);
    CHECK(mlx90614_read_ambient_c_x10(&dev, &t) == MLX_OK && bus.last_cmd == MLX90614_RAM_TA);
    CHECK(mlx90614_probe(&dev) == MLX_OK);

    bus.corrupt_pec = 1; t = 1234;
    CHECK(mlx90614_read_object_c_x10(&dev, &t) == MLX_ERR_PEC && t == 1234 && dev.pec_errors == 1);
    bus.corrupt_pec = 0; bus.fail = 1;
    CHECK(mlx90614_read_object_c_x10(&dev, &t) == MLX_ERR_BUS && dev.bus_errors == 1);
    bus.fail = 0; bus.value = 0x8000 | 0x3AF3;
    CHECK(mlx90614_read_object_c_x10(&dev, &t) == MLX_ERR_FLAG && dev.flag_errors == 1);
    bus.value = 0x0010;
    CHECK(mlx90614_read_object_c_x10(&dev, &t) == MLX_ERR_RANGE);
    /* 10,000 reads in a row, no hang, counters consistent */
    bus.value = 0x3AF3;
    for (int i = 0; i < 10000; i++) CHECK(mlx90614_read_object_c_x10(&dev, &t) == MLX_OK);
    CHECK(dev.reads == 10007);
}

/* ---------------------------------------------------------------- EMC2101 helpers */

TEST(emc2101_helpers)
{
    CHECK(emc2101_pct_to_setting(0) == 0 && emc2101_pct_to_setting(100) == 63 && emc2101_pct_to_setting(50) == 32);
    CHECK(emc2101_count_to_rpm(0xFFFF) == 0 && emc2101_count_to_rpm(0) == 0);
    CHECK(emc2101_count_to_rpm(2700) == 2000);
}

/* ---------------------------------------------------------------- buttons */

static btn_press_t press_for(btn_classifier_t *c, uint8_t b, uint32_t t0, uint32_t held)
{
    btn_edge_t down = { b, true, t0 }, up = { b, false, t0 + held };
    btn_classify(c, &down);
    return btn_classify(c, &up);
}

TEST(button_classification)
{
    btn_classifier_t c; btn_classifier_init(&c);
    CHECK(press_for(&c, BTN_POWER, 1000, 120) == BTN_PRESS_SHORT);
    CHECK(press_for(&c, BTN_POWER, 3000, 499) == BTN_PRESS_SHORT);
    CHECK(press_for(&c, BTN_POWER, 5000, 500) == BTN_PRESS_IGNORED);
    CHECK(press_for(&c, BTN_POWER, 7000, 1499) == BTN_PRESS_IGNORED);
    CHECK(press_for(&c, BTN_CALIBRATE, 9000, 1500) == BTN_PRESS_LONG);
    CHECK(press_for(&c, BTN_FLIP, 12000, 4000) == BTN_PRESS_LONG);
    /* bounce: extra edges within 30 ms are ignored, press still classified once */
    btn_edge_t e1 = { BTN_POWER, true, 20000 }, b1 = { BTN_POWER, false, 20005 }, b2 = { BTN_POWER, true, 20012 },
               up = { BTN_POWER, false, 20200 }, bounce_after = { BTN_POWER, true, 20210 };
    CHECK(btn_classify(&c, &e1) == BTN_PRESS_NONE);
    CHECK(btn_classify(&c, &b1) == BTN_PRESS_NONE && btn_classify(&c, &b2) == BTN_PRESS_NONE);
    CHECK(btn_classify(&c, &up) == BTN_PRESS_SHORT);
    CHECK(btn_classify(&c, &bounce_after) == BTN_PRESS_NONE);
    /* 100 presses -> exactly 100 events */
    int events = 0;
    for (int i = 0; i < 100; i++) events += press_for(&c, BTN_FLIP, 30000 + i * 1000, 100) == BTN_PRESS_SHORT;
    CHECK(events == 100);
    btn_edge_t bad = { 9, true, 1 };
    CHECK(btn_classify(&c, &bad) == BTN_PRESS_NONE);
}

/* ---------------------------------------------------------------- thermal */

TEST(thermal_over_temperature_and_clear)
{
    th_supervisor_t s; th_init(&s);
    CHECK(th_sample(&s, true, 850) == TH_EVT_NONE && th_led_allowed(&s));
    CHECK(th_sample(&s, true, 905) == TH_EVT_NONE);
    CHECK(th_sample(&s, true, 905) == TH_EVT_NONE);
    CHECK(th_sample(&s, true, 905) == TH_EVT_OVER_TEMP_ENTER);   /* third consecutive */
    CHECK(!th_led_allowed(&s) && th_fan_duty_pct(&s) == 100);
    /* a dip resets the hot counter before 3 */
    th_supervisor_t s2; th_init(&s2);
    th_sample(&s2, true, 950); th_sample(&s2, true, 950); th_sample(&s2, true, 890);
    CHECK(th_sample(&s2, true, 950) == TH_EVT_NONE && s2.state == TH_NORMAL);
    /* clearing needs 30 s continuously below 80 C: 299 samples is not enough */
    for (int i = 0; i < 299; i++) CHECK(th_sample(&s, true, 790) == TH_EVT_NONE);
    CHECK(s.state == TH_OVER_TEMP);
    CHECK(th_sample(&s, true, 790) == TH_EVT_OVER_TEMP_CLEAR && th_led_allowed(&s));
    /* a reading at 80 C or above restarts the hold timer */
    th_init(&s); for (int i = 0; i < 3; i++) th_sample(&s, true, 950);
    for (int i = 0; i < 200; i++) th_sample(&s, true, 790);
    th_sample(&s, true, 800);
    for (int i = 0; i < 299; i++) CHECK(th_sample(&s, true, 790) == TH_EVT_NONE);
    CHECK(th_sample(&s, true, 790) == TH_EVT_OVER_TEMP_CLEAR);
    /* cutoff latency: 3 samples at 100 ms = 300 ms, inside the 2 s specification */
    CHECK(TH_OVER_TEMP_SAMPLES * TH_SAMPLE_PERIOD_MS <= 2000);
}

TEST(thermal_sensor_fault_latches)
{
    th_supervisor_t s; th_init(&s);
    for (int i = 0; i < 19; i++) CHECK(th_sample(&s, false, 0) == TH_EVT_NONE);
    CHECK(th_led_allowed(&s));                                  /* 19 failures: still ok */
    th_sample(&s, true, 400);                                   /* one good read resets */
    for (int i = 0; i < 19; i++) th_sample(&s, false, 0);
    CHECK(th_sample(&s, false, 0) == TH_EVT_SENSOR_FAULT && !th_led_allowed(&s));
    CHECK(th_sample(&s, true, 300) == TH_EVT_NONE && s.state == TH_SENSOR_FAULT);  /* latched */
    CHECK(TH_SENSOR_FAIL_SAMPLES * TH_SAMPLE_PERIOD_MS == 2000);
}

TEST(thermal_fan_curve)
{
    th_supervisor_t s; th_init(&s);
    CHECK(th_fan_duty_pct(&s) == 100);                          /* no reading yet: safe default */
    th_sample(&s, true, 200); CHECK(th_fan_duty_pct(&s) == 20);
    th_sample(&s, true, 550); CHECK(th_fan_duty_pct(&s) == 60);
    th_sample(&s, true, 800); CHECK(th_fan_duty_pct(&s) == 100);
}

/* ---------------------------------------------------------------- control */

TEST(control_power_calibrate_flip_brightness)
{
    ctl_t c; ctl_outputs_t o;
    ctl_init(&c, 2, false);
    ctl_boot_done(&c, true, &o);
    CHECK(c.state == CTL_OFF && !o.led_enable && o.indicator == IND_OFF && o.send == CTL_SEND_BRIGHTNESS && o.send_arg == 2);

    ctl_on_button(&c, BTN_POWER, BTN_PRESS_SHORT, &o);
    CHECK(c.state == CTL_ON && o.led_enable && o.led_duty_pct == 50);
    ctl_on_button(&c, BTN_POWER, BTN_PRESS_LONG, &o);
    CHECK(c.brightness_level == 3 && o.led_duty_pct == 75 && o.send == CTL_SEND_BRIGHTNESS);
    ctl_on_button(&c, BTN_POWER, BTN_PRESS_LONG, &o); ctl_on_button(&c, BTN_POWER, BTN_PRESS_LONG, &o);
    CHECK(c.brightness_level == 1 && o.led_duty_pct == 25);      /* wraps 4 -> 1 */
    ctl_on_button(&c, BTN_FLIP, BTN_PRESS_SHORT, &o);
    CHECK(c.flip && o.send == CTL_SEND_FLIP && o.send_arg == 1);
    ctl_on_button(&c, BTN_CALIBRATE, BTN_PRESS_SHORT, &o);
    CHECK(c.state == CTL_ON && o.send == CTL_SEND_NONE);         /* short calibrate: nothing */

    ctl_on_button(&c, BTN_CALIBRATE, BTN_PRESS_LONG, &o);
    CHECK(c.state == CTL_CALIBRATING && o.send == CTL_SEND_CAL_START && o.led_duty_pct == CTL_CAL_BRIGHTNESS_PCT && o.indicator == IND_GREEN_SLOW);
    ctl_on_button(&c, BTN_FLIP, BTN_PRESS_SHORT, &o);
    CHECK(c.flip && o.send == CTL_SEND_NONE);                    /* flip ignored while calibrating */
    ctl_on_link(&c, WP_MSG_READY, NULL, &o);
    CHECK(c.state == CTL_ON && o.led_duty_pct == 25);            /* brightness restored */

    ctl_on_button(&c, BTN_CALIBRATE, BTN_PRESS_LONG, &o);
    ctl_on_button(&c, BTN_CALIBRATE, BTN_PRESS_LONG, &o);
    CHECK(c.state == CTL_ON && o.send == CTL_SEND_CAL_ABORT);    /* second hold aborts */

    ctl_on_button(&c, BTN_CALIBRATE, BTN_PRESS_LONG, &o);
    for (int i = 0; i < 1999; i++) ctl_on_tick(&c, &o);
    CHECK(c.state == CTL_CALIBRATING);
    ctl_on_tick(&c, &o);
    CHECK(c.state == CTL_ON);                                     /* 200 s timeout */

    ctl_on_button(&c, BTN_POWER, BTN_PRESS_SHORT, &o);
    CHECK(c.state == CTL_OFF);
}

TEST(control_thermal_priority)
{
    ctl_t c; ctl_outputs_t o;
    ctl_init(&c, 4, false); ctl_boot_done(&c, true, &o);
    ctl_on_button(&c, BTN_POWER, BTN_PRESS_SHORT, &o);
    ctl_on_button(&c, BTN_CALIBRATE, BTN_PRESS_LONG, &o);
    /* over-temperature from Calibrating: LED off at once, fault message, fans full */
    for (int i = 0; i < 3; i++) {
        th_event_t e = th_sample(&c.thermal, true, 950);
        ctl_on_thermal(&c, e, &o);
    }
    CHECK(c.state == CTL_OVER_TEMP && !o.led_enable && o.fan_duty_pct == 100 && o.indicator == IND_RED_FAST);
    CHECK(o.send == CTL_SEND_FAULT && o.send_arg == WP_FAULT_CODE_OVER_TEMPERATURE);
    ctl_on_button(&c, BTN_POWER, BTN_PRESS_SHORT, &o);
    CHECK(c.state == CTL_OVER_TEMP && !o.led_enable);            /* power ignored */
    for (int i = 0; i < 300; i++) ctl_on_thermal(&c, th_sample(&c.thermal, true, 700), &o);
    CHECK(c.state == CTL_OFF && o.send == CTL_SEND_FAULT && o.send_arg == WP_FAULT_CODE_NONE);
    /* sensor fault from On: latched, power cycle only */
    ctl_on_button(&c, BTN_POWER, BTN_PRESS_SHORT, &o);
    for (int i = 0; i < 20; i++) ctl_on_thermal(&c, th_sample(&c.thermal, false, 0), &o);
    CHECK(c.state == CTL_FAULT && o.indicator == IND_RED_SOLID && !o.led_enable);
    ctl_on_button(&c, BTN_POWER, BTN_PRESS_SHORT, &o);
    CHECK(c.state == CTL_FAULT);
    /* boot with a failed probe goes straight to Fault */
    ctl_init(&c, 4, false); ctl_boot_done(&c, false, &o);
    CHECK(c.state == CTL_FAULT && o.send == CTL_SEND_FAULT && o.send_arg == WP_FAULT_CODE_SENSOR);
}

int main(void)
{
    crc8_matches_python_and_examples_run();
    pack_unpack_round_trip_with_sign_extension_run();
    decoder_ten_thousand_frames_random_chunks_run();
    decoder_drops_corrupt_and_recovers_run();
    mlx90614_conversion_and_pec_run();
    mlx90614_reads_and_rejects_run();
    emc2101_helpers_run();
    button_classification_run();
    thermal_over_temperature_and_clear_run();
    thermal_sensor_fault_latches_run();
    thermal_fan_curve_run();
    control_power_calibrate_flip_brightness_run();
    control_thermal_priority_run();
    printf("\n%d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
