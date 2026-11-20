# Warpei UART protocol

Single source of truth for the link between the ROCK 5B (Python,
`sbc/warpei/link/uart.py`) and the ESP32 (C, `firmware/main/link_uart.c`).
Both sides implement this document; change the document first. It matches
Report Sections 7.1.2, 7.2, 7.5 and 7.6.

Division of responsibility (Report 7.1): the ESP32 sends events upward
(button gestures, temperature, faults) and the ROCK 5B sends state downward
(calibrating, ready, error). The ROCK 5B never controls the LED, and the
ESP32 never touches video.

## Physical link

| Item | Value |
| --- | --- |
| Signals | ESP32 TX → ROCK 5B RX, ESP32 RX ← ROCK 5B TX, common ground |
| Logic level | 3.3 V on both boards (confirm the ROCK 5B header pins before wiring) |
| Rate | 115200 baud, 8 data bits, no parity, 1 stop bit |
| Flow control | None |
| ESP32 pins | UART2: TX GPIO17, RX GPIO16 (change in `sdkconfig.defaults` if the PCB differs) |
| ROCK 5B device | `/dev/ttyS2`, or a USB-serial adapter `/dev/ttyUSB0` during bring-up |

The largest frame (37 bytes) takes about 3.2 ms at 115200 baud.

## Frame format (Report Figure 7.5.1)

Every message is one frame. Multi-byte integers are little-endian.

| Offset | Size | Field | Value |
| --- | --- | --- | --- |
| 0 | 1 | Start | `0xA5` |
| 1 | 1 | ID | message identifier, see below |
| 2 | 1 | Length | payload bytes, 0 to 32 |
| 3 | N | Payload | per message |
| 3+N | 1 | CRC-8 | over ID, Length and every payload byte |

Maximum frame size is 37 bytes (1 + 1 + 1 + 32 + 1 + 1 reserved for a
future sequence byte; implementations must accept up to 37). A receiver
discards bytes until it sees `0xA5`, reads ID and Length, rejects
Length > 32, reads the payload and CRC, and drops the frame on a CRC
mismatch. Resynchronising on `0xA5` means a corrupted frame can be lost
but never misread as a different command.

### CRC-8

The same routine the MLX90614 driver uses for its packet error check, so
the firmware carries one implementation: polynomial `0x07`
(x⁸ + x² + x + 1), initial value `0x00`, no reflection, no final XOR,
computed over ID, Length and the payload bytes in order.

Reference implementation:

```
uint8_t crc8(const uint8_t *data, size_t n) {
    uint8_t crc = 0;
    for (size_t i = 0; i < n; i++) {
        crc ^= data[i];
        for (int b = 0; b < 8; b++)
            crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
    }
    return crc;
}
```

Test vector: `crc8("123456789")` = `0xF4`.

## Messages

Direction E→R is ESP32 to ROCK 5B; R→E is the reverse.

| ID | Name | Direction | Payload | Meaning |
| --- | --- | --- | --- | --- |
| `0x01` | HEARTBEAT | E→R | `u8 fw_state` | Sent every 1 s. Carries the firmware state (Table below). |
| `0x02` | HEARTBEAT_REPLY | R→E | `u8 app_state` | Sent in reply to every HEARTBEAT within 100 ms. Carries the application state. |
| `0x03` | BUTTON | E→R | `u8 command` | A classified button command (Table below), not a raw press. |
| `0x04` | TEMPERATURE | E→R | `i16 object_c_x10, i16 ambient_c_x10, u8 fan_pct, u16 fan_rpm` | Sent every 1 s. Tenths of °C. |
| `0x05` | FAULT | E→R | `u8 fault_code, i16 object_c_x10` | Sent when a fault is entered or cleared (`fault_code` 0 = cleared). The LED enable is already de-asserted before this is sent. |
| `0x06` | BRIGHTNESS | E→R | `u8 level` | Current LED brightness level 1–4 (25/50/75/100 %), sent on change and at boot. Informational: brightness is owned by the ESP32. |
| `0x10` | CAL_START | E→R | none | Long press of Calibrate: start a calibration. |
| `0x11` | CAL_ABORT | E→R | none | Second long press during calibration: abort. |
| `0x12` | FLIP | E→R | `u8 flip` | Short press of Flip: 1 = mirrored, 0 = normal. |
| `0x20` | CAL_STATE | R→E | `u8 app_state` | Application state change (calibrating, ready, error). Drives the status indicator. |
| `0x21` | READY | R→E | `u16 rms_before_x10, u16 rms_after_x10, u8 reduction_pct` | Calibration finished and stored. RMS in tenths of a camera pixel. |
| `0x22` | CAL_ERROR | R→E | `u8 error_code` | Calibration failed; the previous calibration (if any) is kept. |
| `0x7F` | ACK | both | `u8 acked_id` | Reply to CAL_START, CAL_ABORT and FLIP within 100 ms. |

### Button commands (`BUTTON.command`, Report Table 7.2.6.1)

Presses are classified by the firmware on release: short is under 500 ms,
long is 1.5 s or more, anything between is discarded. Debounce ignores edges
within 30 ms of the previous edge.

| Value | Button | Press | Action |
| --- | --- | --- | --- |
| 1 | Power | short | Toggle On / Off (handled on the ESP32, reported for the status card) |
| 2 | Power | long | Step LED brightness through the four levels (On state only) |
| 3 | Calibrate | long | Start calibration (sent as CAL_START), or abort if already calibrating (CAL_ABORT) |
| 4 | Flip | short | Toggle image flip (sent as FLIP) |

Calibrate short press and Flip long press have no action and are not sent.

### Firmware states (`HEARTBEAT.fw_state`, Report Figure 7.2.3)

| Value | State | Indicator |
| --- | --- | --- |
| 0 | Booting | green slow blink |
| 1 | Off | both LEDs off |
| 2 | On | green solid |
| 3 | Calibrating | green slow blink |
| 4 | Over-temperature | red fast blink |
| 5 | Fault | red solid |

### Application states (`HEARTBEAT_REPLY.app_state`, `CAL_STATE.app_state`)

| Value | State |
| --- | --- |
| 0 | Booting |
| 1 | No source (status card shown) |
| 2 | Passthrough (no calibration loaded) |
| 3 | Warped (calibration loaded) |
| 4 | Calibrating |
| 5 | Error |

### Fault codes (`FAULT.fault_code`, Report 7.2.2)

| Value | Fault | Entered when | Cleared when |
| --- | --- | --- | --- |
| 0 | None | | |
| 1 | Over-temperature | 3 consecutive object readings above 90 °C | Readings below 80 °C for 30 s (automatic; 10 °C hysteresis). Exits to Off. |
| 2 | Sensor fault | 20 consecutive failed or PEC-rejected reads (2 s), watchdog fired, or boot probe failed | Power cycle only |

LED power is cut by the ESP32 within 2 s of any fault, independent of the
ROCK 5B and of this link. There is no clear-fault command: the firmware
recovers on its own when it is safe to.

### Calibration error codes (`CAL_ERROR.error_code`, Report 7.3)

| Value | Name | Meaning |
| --- | --- | --- |
| 1 | DETECT_FAIL | Grid not found after three detection attempts |
| 2 | ACCURACY | Verified RMS reduction below 50 % |
| 3 | TIMEOUT | Calibration exceeded the 180 s budget |
| 4 | ABORTED | CAL_ABORT received |
| 5 | CAMERA | Camera returned no frame |

## Timing (Report 7.2.7, 7.5)

| Item | Value |
| --- | --- |
| Heartbeat period | 1 s, ESP32 → ROCK 5B |
| Heartbeat reply deadline | 100 ms |
| Link down | No reply for 5 s. The ESP32 changes the status indicator only; LED and thermal behaviour are unaffected. The ROCK 5B shows "controller offline" on the status card after 5 s without a HEARTBEAT. |
| TEMPERATURE period | 1 s |
| ACK deadline | 100 ms; the sender retries twice, then logs an error |
| Calibration timeout (firmware) | 200 s: Calibrating exits to On if neither READY nor CAL_ERROR arrives |
| Thermal sample period | 100 ms |

## Sequences (Report Figure 7.1.2)

**Calibration.** ESP32 sends CAL_START → ROCK 5B replies ACK, sends
CAL_STATE(4), stops video, runs the routine → on success sends READY with
both RMS values and CAL_STATE(3); on failure sends CAL_ERROR and
CAL_STATE(3) or CAL_STATE(2) depending on whether a prior calibration
exists. The ESP32 forces calibration brightness for the duration and
restores the stored level on exit.

**Thermal fault.** ESP32 de-asserts LED enable, then sends FAULT(1). The
ROCK 5B shows the fault on the status card. Nothing on the link is required
for the cutoff.

**Heartbeat.** ESP32 sends HEARTBEAT every 1 s; ROCK 5B answers with
HEARTBEAT_REPLY. Either side treats 5 s of silence as link down.

## Example frames

CAL_START: `A5 10 00 57`  (crc8 of `10 00` = 0x57)

FLIP mirrored: `A5 12 01 01 66`  (crc8 of `12 01 01` = 0x66)

HEARTBEAT, firmware On: `A5 01 01 02 70`  (crc8 of `01 01 02` = 0x70)

## Code generation

The C header (`firmware/components/protocol/include/warpei_protocol.h`) and
the Python module (`sbc/warpei/link/protocol.py`) are to be generated from
`protocol/messages.json` by `protocol/generate.py` (Phase 5), so the two
sides compile against one definition. Until then this document is the
definition and both implementations must be checked against it by hand.