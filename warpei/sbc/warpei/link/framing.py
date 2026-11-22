"""Frame encoding and byte-wise decoding for the UART link (Report 7.5).

Frame: START(0xA5) ID LEN PAYLOAD[LEN] CRC8, little-endian fields, CRC over
ID, LEN and PAYLOAD. The decoder is fed one byte (or chunk) at a time and
yields complete, CRC-checked frames; anything that fails resynchronises on
the next start byte, so a corrupted frame is dropped, never misread.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from . import protocol as P


def crc8(data: bytes, crc: int = P.CRC_INIT) -> int:
    """CRC-8, polynomial 0x07, no reflection: the MLX90614 PEC routine."""
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ P.CRC_POLY) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


@dataclass(frozen=True)
class Message:
    id: int
    values: dict

    @property
    def name(self) -> str:
        return P.MESSAGES[self.id].name if self.id in P.MESSAGES else f"0x{self.id:02X}"

    def __getattr__(self, item):
        try:
            return self.values[item]
        except KeyError:
            raise AttributeError(item) from None


def encode(msg_id: int, **fields) -> bytes:
    """Build a complete frame for a known message."""
    d = P.MESSAGES[msg_id]
    missing = set(d.fields) - set(fields)
    extra = set(fields) - set(d.fields)
    if missing or extra:
        raise ValueError(f"{d.name}: missing {sorted(missing)}, unexpected {sorted(extra)}")
    payload = struct.pack(d.fmt, *(fields[f] for f in d.fields))
    body = bytes([msg_id, len(payload)]) + payload
    return bytes([P.START_BYTE]) + body + bytes([crc8(body)])


def encode_by_name(name: str, **fields) -> bytes:
    return encode(P.BY_NAME[name].id, **fields)


def decode_payload(msg_id: int, payload: bytes) -> Message:
    d = P.MESSAGES.get(msg_id)
    if d is None:
        raise ValueError(f"unknown message id 0x{msg_id:02X}")
    if len(payload) != d.length:
        raise ValueError(f"{d.name}: payload {len(payload)} bytes, expected {d.length}")
    return Message(msg_id, dict(zip(d.fields, struct.unpack(d.fmt, payload))))


class Decoder:
    """Incremental frame parser. Feed bytes, collect Messages.

    Counters make link tests measurable: frames, crc_errors, bad_length,
    unknown_id, resyncs.
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self.frames = 0
        self.crc_errors = 0
        self.bad_length = 0
        self.unknown_id = 0
        self.resyncs = 0

    def feed(self, data: bytes) -> list[Message]:
        self._buf.extend(data)
        out: list[Message] = []
        while True:
            # 1. find a start byte
            start = self._buf.find(P.START_BYTE)
            if start < 0:
                if self._buf:
                    self.resyncs += 1
                self._buf.clear()
                return out
            if start > 0:
                self.resyncs += 1
                del self._buf[:start]
            # 2. need id and length
            if len(self._buf) < 3:
                return out
            msg_id, length = self._buf[1], self._buf[2]
            if length > P.MAX_PAYLOAD:
                self.bad_length += 1
                del self._buf[0]            # not a real start; resync on the next byte
                continue
            total = 3 + length + 1
            if len(self._buf) < total:
                return out
            body = bytes(self._buf[1:3 + length])
            if crc8(body) != self._buf[3 + length]:
                self.crc_errors += 1
                del self._buf[0]
                continue
            del self._buf[:total]
            self.frames += 1
            try:
                out.append(decode_payload(msg_id, body[2:]))
            except ValueError:
                self.unknown_id += 1
        # unreachable
