/* Thermal supervisor logic (Report 7.2.2, 7.2.3). Pure C, host-tested.
 *
 * Fed one sample every 100 ms. Decides:
 *   over-temperature: 3 consecutive object readings above 90.0 C; clears
 *                     after readings below 80.0 C for 30 s (hysteresis)
 *   sensor fault:     20 consecutive failed or PEC-rejected reads (2 s),
 *                     latched until power cycle
 *   fan duty:         curve on temperature; 100% in any fault
 */
#ifndef THERMAL_LOGIC_H
#define THERMAL_LOGIC_H

#include <stdint.h>
#include <stdbool.h>

#define TH_SAMPLE_PERIOD_MS     100
#define TH_OVER_TEMP_C_X10      900
#define TH_OVER_TEMP_SAMPLES    3
#define TH_CLEAR_C_X10          800
#define TH_CLEAR_HOLD_MS        30000
#define TH_SENSOR_FAIL_SAMPLES  20
#define TH_FAN_MIN_PCT          20
#define TH_FAN_FULL_C_X10       750     /* 100% duty at and above 75 C */
#define TH_FAN_MIN_C_X10        350     /* minimum duty at and below 35 C */

typedef enum { TH_NORMAL = 0, TH_OVER_TEMP, TH_SENSOR_FAULT } th_state_t;

typedef enum {
    TH_EVT_NONE = 0,
    TH_EVT_OVER_TEMP_ENTER,
    TH_EVT_OVER_TEMP_CLEAR,
    TH_EVT_SENSOR_FAULT,
} th_event_t;

typedef struct {
    th_state_t state;
    uint8_t  consecutive_hot;
    uint8_t  consecutive_fail;
    uint32_t below_clear_ms;
    int16_t  last_c_x10;
    bool     have_reading;
} th_supervisor_t;

void th_init(th_supervisor_t *s);

/* read_ok: the sensor returned a valid, PEC-checked value in c_x10.
 * Returns an event when the state changes. */
th_event_t th_sample(th_supervisor_t *s, bool read_ok, int16_t c_x10);

/* LED may be powered only in TH_NORMAL. */
bool th_led_allowed(const th_supervisor_t *s);

/* Fan duty for the current state and temperature. */
uint8_t th_fan_duty_pct(const th_supervisor_t *s);

#endif
