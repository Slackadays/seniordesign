/* Sensor and fan task (Report 7.2.3): reads the MLX90614 every 100 ms
 * through the student driver, runs the thermal logic, drives the EMC2101,
 * posts events to the control task and TEMPERATURE messages to the link. */
#ifndef THERMAL_SUPERVISOR_H
#define THERMAL_SUPERVISOR_H

#include <stdint.h>
#include <stdbool.h>

/* Returns true if the boot probe of the sensor succeeded. */
bool thermal_start(void);
void thermal_set_fan_request(uint8_t pct);   /* control task's request; supervisor may raise it */
int16_t thermal_last_object_c_x10(void);

#endif
