# Warpei UART protocol

Single source of truth for the link between the ROCK 5B (Python,
`sbc/warpei/link/uart.py`) and the ESP32 (C, `firmware/main/link_uart.c`).

## Physical link

| Item | Value |
| --- | --- |
| Signals | ESP32 TX → ROCK 5B RX, ESP32 RX ← ROCK 5B TX, common ground |
| Logic level | 3.3 V on both boards (confirm the ROCK 5B header pins before wiring) |
| Rate | 115200 baud, 8 data bits, no parity, 1 stop bit |
| Flow control | None |
| ESP32 pins | UART2: TX GPIO17, RX GPIO16 (change in `sdkconfig.defaults` if the PCB differs) |
| ROCK 5B device | `/dev/ttyS2` or a USB-serial adapter `/dev/ttyUSB0` during bring-up |

A 16-byte frame takes 1.4 ms at 115200 baud.

## Frame format

Every message is one frame. Multi-byte integers are little-endian.

| Offset | Size | Field | Value |
| --- | --- | --- | --- |
| 0 | 1 | Start | `0xA5` |
| 1 | 1 | Type | message type, see below |
| 2 | 1 | Length | payload bytes, 0 to 32 |
| 3 | N | Payload | per message type |
| 3+N | 1 | Checksum | XOR of Type, Length, and every payload byte |

Maximum frame size is 36 bytes. A receiver discards bytes until it sees
`0xA5`, then reads Type and Length, rejects Length > 32, reads the payload
and checksum, and drops the frame on a checksum mismatch. Resynchronising
on `0xA5` means a corrupted frame costs at most one message.

## Message types

Direction E→R is ESP32 to ROCK 5B; R→E is the reverse.

| Type | Name | Direction | Payload | Meaning |
| --- | --- | --- | --- | --- |
| `0x01` | HEARTBEAT | both | `u8 state` | Sent every 500 ms by each side. Carries the sender's state code. |
| `0x02` | BUTTON | E→R | `u8 button, u8 action` | A debounced button event. |
| `0x03` | STATUS | E→R | `i16 object_c_x10, i16 ambient_c_x10, u8 fan_pct, u16 fan_rpm, u8 led_on, u8 fault` | Sent every 1 s and on any change of `fault` or `led_on`. Temperatures in tenths of °C. |
| `0x04` | FAULT | E→R | `u8 fault_code, i16 object_c_x10` | Sent immediately when a fault latches or clears (`fault_code` 0 = cleared). |
| `0x10` | SET_LED | R→E | `u8 on` | Request LED power on (1) or off (0). The ESP32 refuses with a FAULT reply if a fault is latched. |
| `0x11` | SET_FAN | R→E | `u8 percent` | Fan duty 0 to 100. The thermal supervisor may override upward. |
| `0x12` | CAL_STATE | R→E | `u8 state` | ROCK 5B calibration state, for the status LED. |
| `0x13` | CLEAR_FAULT | R→E | none | Ask the ESP32 to clear a latched fault. Honoured only if the temperature is below the clear threshold. |
| `0x7F` | ACK | both | `u8 acked_type, u8 result` | Reply to every R→E request. `result` 0 = ok, 1 = rejected, 2 = bad payload. |

### Button codes (`BUTTON.button`)

| Value | Button |
| --- | --- |
| 1 | Power |
| 2 | Calibrate |
| 3 | Flip image |

### Button actions (`BUTTON.action`)

| Value | Action |
| --- | --- |
| 1 | Short press (released before 2 s) |
| 2 | Long press (held 2 s or more; sent once when the hold time is reached) |

### Fault codes (`FAULT.fault_code`, `STATUS.fault`)

| Value | Fault | Set when | Cleared when |
| --- | --- | --- | --- |
| 0 | None | | |
| 1 | Over-temperature | 3 consecutive object readings above 90 °C | CLEAR_FAULT received and object below 70 °C |
| 2 | Sensor failure | 5 consecutive MLX90614 read errors (timeout or bad PEC) | A valid reading, then CLEAR_FAULT |
| 3 | Fan stall | Fan RPM 0 for 3 s while duty > 20% | RPM recovers, then CLEAR_FAULT |

LED power is cut by the ESP32 within 2 s of any fault, independent of the
ROCK 5B. The ROCK 5B cannot turn the LED on while a fault is latched.

### State codes (`HEARTBEAT.state`, `CAL_STATE.state`)

| Value | ROCK 5B state | ESP32 state |
| --- | --- | --- |
| 0 | Booting | Booting |
| 1 | Idle | Idle, LED off |
| 2 | Projecting pattern | LED on |
| 3 | Capturing | — |
| 4 | Solving | — |
| 5 | Verifying | — |
| 6 | Running (corrected video) | — |
| 7 | Failed | Fault latched |

## Timing

| Item | Value |
| --- | --- |
| Heartbeat period | 500 ms each way |
| Heartbeat loss | 3 missed (1.5 s): the ESP32 keeps the LED state but flags the status LED; the ROCK 5B logs a warning and shows "controller offline" |
| STATUS period | 1 s |
| ACK deadline | 100 ms; the ROCK 5B retries a request twice, then logs an error |
| Thermal sample period | 100 ms |

## Example frames

SET_LED on: `A5 10 01 01 10`  (checksum = 0x10 ^ 0x01 ^ 0x01 = 0x10)

BUTTON calibrate short press: `A5 02 02 02 01 01`  (checksum = 0x02 ^ 0x02 ^ 0x02 ^ 0x01 = 0x01)

HEARTBEAT from ROCK 5B in Running state: `A5 01 01 06 06`

## Test plan (task 5.6)

1. Loopback: ROCK 5B TX to RX, send and receive 10,000 random frames, expect 0 accepted corruptions.
2. Inject one wrong checksum byte per 100 frames, expect every one dropped and the next frame still received.
3. Unplug the ESP32, expect "controller offline" within 1.5 s on the ROCK 5B.
4. Press Calibrate on the ESP32, expect the ROCK 5B to enter Projecting within 100 ms.
