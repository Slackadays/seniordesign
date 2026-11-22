from __future__ import annotations

import struct
from dataclasses import dataclass

PROTOCOL_VERSION = 2
START_BYTE = 0xA5
MAX_PAYLOAD = 32
MAX_FRAME = 37
CRC_POLY = 0x07
CRC_INIT = 0x00

BAUD = 115200
HEARTBEAT_PERIOD_MS = 1000
HEARTBEAT_REPLY_DEADLINE_MS = 100
LINK_DOWN_MS = 5000
ACK_DEADLINE_MS = 100
ACK_RETRIES = 2
FIRMWARE_CALIBRATION_TIMEOUT_MS = 200000


@dataclass(frozen=True)
class MessageDef:
    id: int
    name: str
    direction: str
    fields: tuple[str, ...]
    fmt: str   # struct format, little-endian

    @property
    def length(self) -> int:
        return struct.calcsize(self.fmt)


MESSAGES: dict[int, MessageDef] = {
    0x01: MessageDef(0x01, "HEARTBEAT", "E2R", ("fw_state",), "<B"),
    0x02: MessageDef(0x02, "HEARTBEAT_REPLY", "R2E", ("app_state",), "<B"),
    0x03: MessageDef(0x03, "BUTTON", "E2R", ("command",), "<B"),
    0x04: MessageDef(0x04, "TEMPERATURE", "E2R", ("object_c_x10", "ambient_c_x10", "fan_pct", "fan_rpm"), "<hhBH"),
    0x05: MessageDef(0x05, "FAULT", "E2R", ("fault_code", "object_c_x10"), "<Bh"),
    0x06: MessageDef(0x06, "BRIGHTNESS", "E2R", ("level",), "<B"),
    0x10: MessageDef(0x10, "CAL_START", "E2R", (), "<"),
    0x11: MessageDef(0x11, "CAL_ABORT", "E2R", (), "<"),
    0x12: MessageDef(0x12, "FLIP", "E2R", ("flip",), "<B"),
    0x20: MessageDef(0x20, "CAL_STATE", "R2E", ("app_state",), "<B"),
    0x21: MessageDef(0x21, "READY", "R2E", ("rms_before_x10", "rms_after_x10", "reduction_pct"), "<HHB"),
    0x22: MessageDef(0x22, "CAL_ERROR", "R2E", ("error_code",), "<B"),
    0x7F: MessageDef(0x7F, "ACK", "both", ("acked_id",), "<B"),
}
BY_NAME: dict[str, MessageDef] = {m.name: m for m in MESSAGES.values()}

MSG_HEARTBEAT = 0x01
MSG_HEARTBEAT_REPLY = 0x02
MSG_BUTTON = 0x03
MSG_TEMPERATURE = 0x04
MSG_FAULT = 0x05
MSG_BRIGHTNESS = 0x06
MSG_CAL_START = 0x10
MSG_CAL_ABORT = 0x11
MSG_FLIP = 0x12
MSG_CAL_STATE = 0x20
MSG_READY = 0x21
MSG_CAL_ERROR = 0x22
MSG_ACK = 0x7F


class ButtonCommand:
    POWER_SHORT = 1
    POWER_LONG = 2
    CALIBRATE_LONG = 3
    FLIP_SHORT = 4
    NAMES = {1: "POWER_SHORT", 2: "POWER_LONG", 3: "CALIBRATE_LONG", 4: "FLIP_SHORT"}


class FwState:
    BOOTING = 0
    OFF = 1
    ON = 2
    CALIBRATING = 3
    OVER_TEMPERATURE = 4
    FAULT = 5
    NAMES = {0: "BOOTING", 1: "OFF", 2: "ON", 3: "CALIBRATING", 4: "OVER_TEMPERATURE", 5: "FAULT"}


class AppState:
    BOOTING = 0
    NO_SOURCE = 1
    PASSTHROUGH = 2
    WARPED = 3
    CALIBRATING = 4
    ERROR = 5
    NAMES = {0: "BOOTING", 1: "NO_SOURCE", 2: "PASSTHROUGH", 3: "WARPED", 4: "CALIBRATING", 5: "ERROR"}


class FaultCode:
    NONE = 0
    OVER_TEMPERATURE = 1
    SENSOR = 2
    NAMES = {0: "NONE", 1: "OVER_TEMPERATURE", 2: "SENSOR"}


class CalError:
    DETECT_FAIL = 1
    ACCURACY = 2
    TIMEOUT = 3
    ABORTED = 4
    CAMERA = 5
    NAMES = {1: "DETECT_FAIL", 2: "ACCURACY", 3: "TIMEOUT", 4: "ABORTED", 5: "CAMERA"}
