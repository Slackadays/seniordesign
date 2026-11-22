#include "thermal_logic.h"
#include <string.h>

void th_init(th_supervisor_t *s)
{
    memset(s, 0, sizeof(*s));
    s->state = TH_NORMAL;
}

th_event_t th_sample(th_supervisor_t *s, bool read_ok, int16_t c_x10)
{
    if (s->state == TH_SENSOR_FAULT) {
        return TH_EVT_NONE;                 /* latched until power cycle */
    }
    if (!read_ok) {
        s->consecutive_hot = 0;
        if (++s->consecutive_fail >= TH_SENSOR_FAIL_SAMPLES) {
            s->state = TH_SENSOR_FAULT;
            return TH_EVT_SENSOR_FAULT;
        }
        return TH_EVT_NONE;
    }
    s->consecutive_fail = 0;
    s->last_c_x10 = c_x10;
    s->have_reading = true;

    if (s->state == TH_NORMAL) {
        if (c_x10 > TH_OVER_TEMP_C_X10) {
            if (++s->consecutive_hot >= TH_OVER_TEMP_SAMPLES) {
                s->state = TH_OVER_TEMP;
                s->below_clear_ms = 0;
                return TH_EVT_OVER_TEMP_ENTER;
            }
        } else {
            s->consecutive_hot = 0;
        }
        return TH_EVT_NONE;
    }
    /* TH_OVER_TEMP: clear only after 30 s continuously below 80 C */
    if (c_x10 < TH_CLEAR_C_X10) {
        s->below_clear_ms += TH_SAMPLE_PERIOD_MS;
        if (s->below_clear_ms >= TH_CLEAR_HOLD_MS) {
            s->state = TH_NORMAL;
            s->consecutive_hot = 0;
            return TH_EVT_OVER_TEMP_CLEAR;
        }
    } else {
        s->below_clear_ms = 0;
    }
    return TH_EVT_NONE;
}

bool th_led_allowed(const th_supervisor_t *s)
{
    return s->state == TH_NORMAL;
}

uint8_t th_fan_duty_pct(const th_supervisor_t *s)
{
    if (s->state != TH_NORMAL || !s->have_reading) {
        return 100;
    }
    int32_t t = s->last_c_x10;
    if (t <= TH_FAN_MIN_C_X10) {
        return TH_FAN_MIN_PCT;
    }
    if (t >= TH_FAN_FULL_C_X10) {
        return 100;
    }
    int32_t span = TH_FAN_FULL_C_X10 - TH_FAN_MIN_C_X10;
    return (uint8_t)(TH_FAN_MIN_PCT + (100 - TH_FAN_MIN_PCT) * (t - TH_FAN_MIN_C_X10) / span);
}
