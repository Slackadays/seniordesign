/* PLACEHOLDER Pin assignment for the Warpei control board (ESP32-WROOM-32E).
 * Update from the PCB schematic before flashing; these are bring-up
 * defaults for a dev board. */
#ifndef WARPEI_PINS_H
#define WARPEI_PINS_H

#define PIN_I2C_SDA        21
#define PIN_I2C_SCL        22
#define I2C_PORT           0

#define PIN_UART_TX        17      /* UART2 to the ROCK 5B RX */
#define PIN_UART_RX        16      /* UART2 from the ROCK 5B TX */
#define UART_PORT          2

#define PIN_BTN_POWER      32      /* arcade switches to ground, internal pull-ups */
#define PIN_BTN_CALIBRATE  33
#define PIN_BTN_FLIP       25

#define PIN_LED_ENABLE     26      /* LED driver enable, active high */
#define PIN_LED_DIM_PWM    27      /* LED driver dimming input, PWM */
#define PIN_IND_GREEN      14      /* status indicator */
#define PIN_IND_RED        12      /* fault indicator */

#define LED_PWM_FREQ_HZ    1000    /* above camera flicker range; raise if the driver allows */

#endif
