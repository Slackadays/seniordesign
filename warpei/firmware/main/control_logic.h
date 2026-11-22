/* Control state machine (Report 7.2.2, Figure 7.2.3). Pure C, host-tested.
 *
 * States: BOOTING, OFF, ON, CALIBRATING, OVER_TEMPERATURE, FAULT.
 * Inputs: button commands, thermal events, link messages, a 100 ms tick.
 * Outputs: LED enable, brightness duty, status indicator pattern, and
 * messages to send to the ROCK 5B, collected in ctl_outputs_t.
 */
#ifndef CONTROL_LOGIC_H
#define CONTROL_LOGIC_H

#include <stdint.h>
#include <stdbool.h>
#include "warpei_protocol.h"
#include "buttons.h"
#include "thermal_logic.h"

#define CTL_TICK_MS               100
#define CTL_CAL_TIMEOUT_MS        WP_FIRMWARE_CALIBRATION_TIMEOUT_MS   /* 200 s */
#define CTL_BRIGHTNESS_LEVELS     4
#define CTL_CAL_BRIGHTNESS_PCT    100      /* fixed level during calibration */

typedef enum {
    CTL_BOOTING = WP_FW_STATE_BOOTING,
    CTL_OFF = WP_FW_STATE_OFF,
    CTL_ON = WP_FW_STATE_ON,
    CTL_CALIBRATING = WP_FW_STATE_CALIBRATING,
    CTL_OVER_TEMP = WP_FW_STATE_OVER_TEMPERATURE,
    CTL_FAULT = WP_FW_STATE_FAULT,
} ctl_state_t;

typedef enum { IND_OFF = 0, IND_GREEN_SOLID, IND_GREEN_SLOW, IND_RED_FAST, IND_RED_SOLID } ctl_indicator_t;

/* Messages the control logic asks the link task to send. */
typedef enum {
    CTL_SEND_NONE = 0,
    CTL_SEND_CAL_START,
    CTL_SEND_CAL_ABORT,
    CTL_SEND_FLIP,
    CTL_SEND_BRIGHTNESS,
    CTL_SEND_FAULT,
} ctl_send_t;

typedef struct {
    bool            led_enable;
    uint8_t         led_duty_pct;
    ctl_indicator_t indicator;
    uint8_t         fan_duty_pct;
    ctl_send_t      send;            /* at most one message per step */
    int32_t         send_arg;        /* flip value, brightness level, fault code */
} ctl_outputs_t;

typedef struct {
    ctl_state_t state;
    uint8_t  brightness_level;       /* 1..4 -> 25/50/75/100 % */
    bool     flip;
    uint32_t cal_elapsed_ms;
    bool     link_up;
    th_supervisor_t thermal;
} ctl_t;

void ctl_init(ctl_t *c, uint8_t stored_brightness_level, bool stored_flip);
void ctl_boot_done(ctl_t *c, bool sensor_probe_ok, ctl_outputs_t *out);

/* Event entry points. Each fills `out` (zeroed first). */
void ctl_on_button(ctl_t *c, uint8_t button, btn_press_t press, ctl_outputs_t *out);
void ctl_on_thermal(ctl_t *c, th_event_t evt, ctl_outputs_t *out);
void ctl_on_link(ctl_t *c, uint8_t msg_id, const int32_t *fields, ctl_outputs_t *out); /* READY / CAL_ERROR */
void ctl_on_tick(ctl_t *c, ctl_outputs_t *out);                                         /* every 100 ms */

uint8_t ctl_brightness_pct(const ctl_t *c);

#endif
