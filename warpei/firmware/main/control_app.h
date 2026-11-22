/* Control task: owns the control state machine, the LED outputs and the
 * indicator; receives button commands, thermal events and link messages
 * through one queue, so the state machine runs on a single task. */
#ifndef CONTROL_APP_H
#define CONTROL_APP_H

#include <stdint.h>
#include "thermal_logic.h"
#include "buttons.h"
#include "wp_frame.h"

int  control_start(void);
void control_post_button(uint8_t button, btn_press_t press);
void control_post_thermal(th_event_t evt, int16_t object_c_x10);
void control_post_link(const wp_message_t *msg);
void control_boot_done(bool sensor_probe_ok);
uint8_t control_current_fw_state(void);

#endif
