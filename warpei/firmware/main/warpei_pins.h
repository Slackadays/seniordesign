/* Pin assignment for the Warpei control board (ESP32-WROOM-32E-N4),
 * taken from the PCB schematic (rev. 2026-11-22, U1 + SW1..SW10, Q1/Q2
 * LED switch, J3 FAN I2C header, J1 USB-B via CH340C).
 *
 * A value of -1 means the board has no such signal; the firmware skips it. */
#ifndef WARPEI_PINS_H
#define WARPEI_PINS_H

/* I2C bus: MLX90614 and EMC2101 (J3 "FAN" header carries 3V3/GND/SCL/SDA).
 * 4.7k pull-ups R4 (SDA) and R5 (SCL) are on the board. */
#define PIN_I2C_SDA        21
#define PIN_I2C_SCL        22
#define I2C_PORT           0

/* Link to the ROCK 5B. The board has no separate UART header: TXD0/RXD0
 * (IO1/IO3) go to the CH340C and out through J1 (USB-B). The ROCK 5B sees it
 * as /dev/ttyUSB0. UART0 is therefore the protocol link, and the ESP-IDF
 * console must be disabled (CONFIG_ESP_CONSOLE_NONE=y in sdkconfig.defaults)
 * so log output cannot corrupt the frame stream. */
#define PIN_UART_TX        1       /* TXD0 -> CH340C RXD */
#define PIN_UART_RX        3       /* RXD0 <- CH340C TXD */
#define UART_PORT          0

/* Buttons: B3F-1000 tactile switches to ground with 10k pull-ups to 3V3
 * (R3, R6..R12). Pressed reads low. Schematic names in comments.
 * SW1 (IO0, BOOT) and SW2 (EN, RESET) are bootloader/reset, not user inputs. */
#define PIN_BTN_POWER      32      /* SW3  USER  */
#define PIN_BTN_CALIBRATE  33      /* SW4  USER2 */
#define PIN_BTN_FLIP       26      /* SW5  USER3 */
#define PIN_BTN_BRIGHT_UP  27      /* SW6  USER4 */
#define PIN_BTN_BRIGHT_DN  18      /* SW7  USER5 */
#define PIN_BTN_SPARE1     19      /* SW8  USER6 (unused) */
#define PIN_BTN_SPARE2     23      /* SW9  USER7 (unused) */
#define PIN_BTN_SPARE3     4       /* SW10 USER8 (unused) */

/* LED: one control line. GPIO25 -> R13 2.2k -> Q2 (2N5551, NPN) -> R15 2.2k
 * -> gate of Q1 (IRF4905, P-channel high-side switch on +24V_IN). R16 47k
 * holds the gate at +24V (off) while the ESP32 is in reset, D1 (12 V zener)
 * clamps Vgs. Driving GPIO25 high turns the LED on, so this pin is active
 * high and PWM on it is the only dimming path. There is no separate enable. */
#define PIN_LED_ENABLE     -1      /* none: enable == PWM duty > 0 */
#define PIN_LED_DIM_PWM    25      /* GPIO25, active high, PWM */

/* Status indicators: not present on this board. */
#define PIN_IND_GREEN      -1
#define PIN_IND_RED        -1

/* Q1 gate sees an RC of roughly R15 (2.2k) x Cgs; 1 kHz keeps the switching
 * edges short relative to the period. Do not raise above a few kHz without
 * checking Q1 temperature. */
#define LED_PWM_FREQ_HZ    1000

#endif
