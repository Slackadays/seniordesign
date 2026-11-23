#include "control_app.h"
#include "control_logic.h"
#include "link_uart.h"
#include "warpei_pins.h"
#include "thermal_supervisor.h"
#include "driver/gpio.h"
#include "driver/ledc.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include <string.h>

static const char *TAG = "control";

typedef enum { EV_BUTTON, EV_THERMAL, EV_LINK, EV_BOOT, EV_TICK } ev_kind_t;
typedef struct {
    ev_kind_t kind;
    uint8_t a;            /* button / thermal event / boot ok */
    uint8_t b;            /* press class */
    int16_t t_x10;
    wp_message_t msg;
} ev_t;

static QueueHandle_t s_q;
static ctl_t s_ctl;
static volatile uint8_t s_fw_state = WP_FW_STATE_BOOTING;

/* ---- NVS: brightness level and flip survive a power cycle ---------------- */

static void nvs_load(uint8_t *level, bool *flip)
{
    nvs_handle_t h;
    *level = CTL_BRIGHTNESS_LEVELS; *flip = false;
    if (nvs_open("warpei", NVS_READONLY, &h) == ESP_OK) {
        uint8_t v;
        if (nvs_get_u8(h, "bright", &v) == ESP_OK) *level = v;
        if (nvs_get_u8(h, "flip", &v) == ESP_OK) *flip = v != 0;
        nvs_close(h);
    }
}

static void nvs_store(uint8_t level, bool flip)
{
    nvs_handle_t h;
    if (nvs_open("warpei", NVS_READWRITE, &h) == ESP_OK) {
        nvs_set_u8(h, "bright", level);
        nvs_set_u8(h, "flip", flip ? 1 : 0);
        nvs_commit(h);
        nvs_close(h);
    }
}

/* ---- outputs ------------------------------------------------------------- */

static void outputs_init(void)
{
    uint64_t mask = 0;
    mask |= PIN_MASK(PIN_LED_ENABLE);
    mask |= PIN_MASK(PIN_IND_GREEN);
    mask |= PIN_MASK(PIN_IND_RED);
    if (mask) {
        gpio_config_t out = { .pin_bit_mask = mask, .mode = GPIO_MODE_OUTPUT };
        gpio_config(&out);
    }
    if (PIN_LED_ENABLE >= 0) gpio_set_level(PIN_LED_ENABLE, 0);
    ledc_timer_config_t timer = {
        .speed_mode = LEDC_LOW_SPEED_MODE, .timer_num = LEDC_TIMER_0,
        .duty_resolution = LEDC_TIMER_10_BIT, .freq_hz = LED_PWM_FREQ_HZ, .clk_cfg = LEDC_AUTO_CLK,
    };
    ledc_timer_config(&timer);
    ledc_channel_config_t ch = {
        .speed_mode = LEDC_LOW_SPEED_MODE, .channel = LEDC_CHANNEL_0, .timer_sel = LEDC_TIMER_0,
        .gpio_num = PIN_LED_DIM_PWM, .duty = 0, .hpoint = 0,
    };
    ledc_channel_config(&ch);
}

static uint32_t s_blink_phase;

static void apply_outputs(const ctl_outputs_t *o)
{
    /* LED enable is the safety output: drive it before anything else. */
    if (PIN_LED_ENABLE >= 0) gpio_set_level(PIN_LED_ENABLE, o->led_enable ? 1 : 0);
    /* With no enable pin (Warpei PCB), duty 0 is the off state. */
    uint32_t duty = o->led_enable ? (1023u * o->led_duty_pct) / 100u : 0;
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, duty);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
    thermal_set_fan_request(o->fan_duty_pct);

    bool slow = (s_blink_phase / 5) % 2 == 0;    /* 1 Hz on a 100 ms tick */
    bool fast = (s_blink_phase / 1) % 2 == 0;    /* 5 Hz */
    bool g = false, r = false;
    switch (o->indicator) {
    case IND_GREEN_SOLID: g = true; break;
    case IND_GREEN_SLOW:  g = slow; break;
    case IND_RED_FAST:    r = fast; break;
    case IND_RED_SOLID:   r = true; break;
    default: break;
    }
    if (PIN_IND_GREEN >= 0) gpio_set_level(PIN_IND_GREEN, g);
    if (PIN_IND_RED >= 0)   gpio_set_level(PIN_IND_RED, r);

    int32_t arg = o->send_arg;
    switch (o->send) {
    case CTL_SEND_CAL_START:  link_send(WP_MSG_CAL_START, NULL, 0); break;
    case CTL_SEND_CAL_ABORT:  link_send(WP_MSG_CAL_ABORT, NULL, 0); break;
    case CTL_SEND_FLIP:       link_send(WP_MSG_FLIP, &arg, 1); break;
    case CTL_SEND_BRIGHTNESS: link_send(WP_MSG_BRIGHTNESS, &arg, 1); break;
    case CTL_SEND_FAULT: {
        int32_t f[2] = { arg, thermal_last_object_c_x10() };
        link_send(WP_MSG_FAULT, f, 2);
        break;
    }
    default: break;
    }
}

/* ---- task ------------------------------------------------------------------ */

static void control_task(void *arg)
{
    (void)arg;
    ev_t ev;
    ctl_outputs_t out;
    for (;;) {
        if (xQueueReceive(s_q, &ev, pdMS_TO_TICKS(CTL_TICK_MS)) != pdTRUE) {
            ev.kind = EV_TICK;
        }
        uint8_t level_before = s_ctl.brightness_level;
        bool flip_before = s_ctl.flip;
        switch (ev.kind) {
        case EV_BOOT:    ctl_boot_done(&s_ctl, ev.a != 0, &out); break;
        case EV_BUTTON:  ctl_on_button(&s_ctl, ev.a, (btn_press_t)ev.b, &out); break;
        case EV_THERMAL: ctl_on_thermal(&s_ctl, (th_event_t)ev.a, &out); break;
        case EV_LINK: {
            int32_t fields[8];
            wp_unpack(ev.msg.id, ev.msg.payload, ev.msg.len, fields, 8);
            ctl_on_link(&s_ctl, ev.msg.id, fields, &out);
            break;
        }
        case EV_TICK:
        default:
            s_blink_phase++;
            s_ctl.link_up = link_is_up();
            ctl_on_tick(&s_ctl, &out);
            break;
        }
        if (s_ctl.brightness_level != level_before || s_ctl.flip != flip_before) {
            nvs_store(s_ctl.brightness_level, s_ctl.flip);
        }
        s_fw_state = (uint8_t)s_ctl.state;
        apply_outputs(&out);
        if (ev.kind != EV_TICK) {
            ESP_LOGI(TAG, "event %d -> state %d led %d duty %d", ev.kind, s_ctl.state, out.led_enable, out.led_duty_pct);
        }
    }
}

static void post(const ev_t *ev)
{
    xQueueSend(s_q, ev, pdMS_TO_TICKS(10));
}

void control_post_button(uint8_t button, btn_press_t press)
{
    ev_t ev = { .kind = EV_BUTTON, .a = button, .b = (uint8_t)press };
    post(&ev);
}

void control_post_thermal(th_event_t evt, int16_t object_c_x10)
{
    ev_t ev = { .kind = EV_THERMAL, .a = (uint8_t)evt, .t_x10 = object_c_x10 };
    /* Thermal events go to the front: they must win over a queued button press. */
    xQueueSendToFront(s_q, &ev, pdMS_TO_TICKS(10));
}

void control_post_link(const wp_message_t *msg)
{
    ev_t ev = { .kind = EV_LINK };
    memcpy(&ev.msg, msg, sizeof ev.msg);
    post(&ev);
}

void control_boot_done(bool sensor_probe_ok)
{
    ev_t ev = { .kind = EV_BOOT, .a = sensor_probe_ok ? 1 : 0 };
    post(&ev);
}

uint8_t control_current_fw_state(void)
{
    return s_fw_state;
}

int control_start(void)
{
    uint8_t level; bool flip;
    nvs_load(&level, &flip);
    ctl_init(&s_ctl, level, flip);
    outputs_init();
    s_q = xQueueCreate(16, sizeof(ev_t));
    return xTaskCreate(control_task, "control", 4096, NULL, 7, NULL) == pdPASS ? 0 : -1;
}
