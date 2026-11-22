#include "control_logic.h"
#include <string.h>

static const uint8_t LEVEL_PCT[CTL_BRIGHTNESS_LEVELS + 1] = { 0, 25, 50, 75, 100 };

uint8_t ctl_brightness_pct(const ctl_t *c)
{
    uint8_t l = c->brightness_level;
    if (l < 1 || l > CTL_BRIGHTNESS_LEVELS) {
        l = CTL_BRIGHTNESS_LEVELS;
    }
    return LEVEL_PCT[l];
}

/* Derive the outputs from the current state. */
static void apply(ctl_t *c, ctl_outputs_t *out)
{
    bool thermal_ok = th_led_allowed(&c->thermal);
    out->fan_duty_pct = th_fan_duty_pct(&c->thermal);
    switch (c->state) {
    case CTL_BOOTING:
        out->led_enable = false; out->led_duty_pct = 0; out->indicator = IND_GREEN_SLOW; break;
    case CTL_OFF:
        out->led_enable = false; out->led_duty_pct = 0; out->indicator = IND_OFF; break;
    case CTL_ON:
        out->led_enable = thermal_ok; out->led_duty_pct = ctl_brightness_pct(c);
        out->indicator = c->link_up ? IND_GREEN_SOLID : IND_GREEN_SLOW; break;
    case CTL_CALIBRATING:
        out->led_enable = thermal_ok; out->led_duty_pct = CTL_CAL_BRIGHTNESS_PCT;
        out->indicator = IND_GREEN_SLOW; break;
    case CTL_OVER_TEMP:
        out->led_enable = false; out->led_duty_pct = 0; out->indicator = IND_RED_FAST;
        out->fan_duty_pct = 100; break;
    case CTL_FAULT:
    default:
        out->led_enable = false; out->led_duty_pct = 0; out->indicator = IND_RED_SOLID;
        out->fan_duty_pct = 100; break;
    }
}

void ctl_init(ctl_t *c, uint8_t stored_brightness_level, bool stored_flip)
{
    memset(c, 0, sizeof(*c));
    c->state = CTL_BOOTING;
    c->brightness_level = (stored_brightness_level >= 1 && stored_brightness_level <= CTL_BRIGHTNESS_LEVELS)
                          ? stored_brightness_level : CTL_BRIGHTNESS_LEVELS;
    c->flip = stored_flip;
    th_init(&c->thermal);
}

void ctl_boot_done(ctl_t *c, bool sensor_probe_ok, ctl_outputs_t *out)
{
    memset(out, 0, sizeof(*out));
    if (!sensor_probe_ok) {
        c->state = CTL_FAULT;                 /* cannot prove the heatsink is safe */
        out->send = CTL_SEND_FAULT;
        out->send_arg = WP_FAULT_CODE_SENSOR;
    } else {
        c->state = CTL_OFF;
        out->send = CTL_SEND_BRIGHTNESS;
        out->send_arg = c->brightness_level;
    }
    apply(c, out);
}

void ctl_on_button(ctl_t *c, uint8_t button, btn_press_t press, ctl_outputs_t *out)
{
    memset(out, 0, sizeof(*out));
    bool is_short = press == BTN_PRESS_SHORT, is_long = press == BTN_PRESS_LONG;

    switch (c->state) {
    case CTL_OFF:
        if (button == BTN_POWER && is_short) {
            c->state = CTL_ON;
        }
        break;
    case CTL_ON:
        if (button == BTN_POWER && is_short) {
            c->state = CTL_OFF;
        } else if (button == BTN_POWER && is_long) {
            c->brightness_level = (uint8_t)(c->brightness_level % CTL_BRIGHTNESS_LEVELS + 1);
            out->send = CTL_SEND_BRIGHTNESS;
            out->send_arg = c->brightness_level;
        } else if (button == BTN_CALIBRATE && is_long) {
            c->state = CTL_CALIBRATING;
            c->cal_elapsed_ms = 0;
            out->send = CTL_SEND_CAL_START;
        } else if (button == BTN_FLIP && is_short) {
            c->flip = !c->flip;
            out->send = CTL_SEND_FLIP;
            out->send_arg = c->flip ? 1 : 0;
        }
        break;
    case CTL_CALIBRATING:
        if (button == BTN_CALIBRATE && is_long) {          /* second hold aborts */
            c->state = CTL_ON;
            out->send = CTL_SEND_CAL_ABORT;
        }
        /* Flip is ignored while calibrating; Power too, to keep the pattern stable */
        break;
    case CTL_OVER_TEMP:
    case CTL_FAULT:
    case CTL_BOOTING:
    default:
        break;                                               /* presses logged, no effect */
    }
    apply(c, out);
}

void ctl_on_thermal(ctl_t *c, th_event_t evt, ctl_outputs_t *out)
{
    memset(out, 0, sizeof(*out));
    switch (evt) {
    case TH_EVT_OVER_TEMP_ENTER:
        if (c->state != CTL_FAULT) {
            c->state = CTL_OVER_TEMP;
            out->send = CTL_SEND_FAULT;
            out->send_arg = WP_FAULT_CODE_OVER_TEMPERATURE;
        }
        break;
    case TH_EVT_OVER_TEMP_CLEAR:
        if (c->state == CTL_OVER_TEMP) {
            c->state = CTL_OFF;                              /* exits to Off, per 7.2.2 */
            out->send = CTL_SEND_FAULT;
            out->send_arg = WP_FAULT_CODE_NONE;
        }
        break;
    case TH_EVT_SENSOR_FAULT:
        c->state = CTL_FAULT;
        out->send = CTL_SEND_FAULT;
        out->send_arg = WP_FAULT_CODE_SENSOR;
        break;
    default:
        break;
    }
    apply(c, out);
}

void ctl_on_link(ctl_t *c, uint8_t msg_id, const int32_t *fields, ctl_outputs_t *out)
{
    (void)fields;
    memset(out, 0, sizeof(*out));
    if (c->state == CTL_CALIBRATING && (msg_id == WP_MSG_READY || msg_id == WP_MSG_CAL_ERROR)) {
        c->state = CTL_ON;
    }
    apply(c, out);
}

void ctl_on_tick(ctl_t *c, ctl_outputs_t *out)
{
    memset(out, 0, sizeof(*out));
    if (c->state == CTL_CALIBRATING) {
        c->cal_elapsed_ms += CTL_TICK_MS;
        if (c->cal_elapsed_ms >= CTL_CAL_TIMEOUT_MS) {
            c->state = CTL_ON;                               /* 200 s guard over the 180 s budget */
        }
    }
    apply(c, out);
}
