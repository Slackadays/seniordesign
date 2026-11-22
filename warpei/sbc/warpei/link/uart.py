"""Runs a reader thread that turns serial bytes into Messages and hands them
to a callback, answers every HEARTBEAT with HEARTBEAT_REPLY, ACKs the
ESP32's requests, tracks link health, and offers send() helpers with ACK
retry for the ROCK 5B's own messages.

Any object with read(n) -> bytes, write(bytes) and a timeout attribute
works as the port, so tests use an in-memory loopback instead of pyserial.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from . import framing
from . import protocol as P

log = logging.getLogger("warpei.link")

REQUESTS_NEEDING_ACK = {P.MSG_CAL_START, P.MSG_CAL_ABORT, P.MSG_FLIP}


def open_serial(device: str, baud: int = P.BAUD, timeout: float = 0.05):
    import serial  # pyserial, imported lazily so tests need not have it
    return serial.Serial(device, baud, timeout=timeout)


class UartLink:
    def __init__(self, port, on_message: Callable[[framing.Message], None] | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.port = port
        self.on_message = on_message
        self.clock = clock
        self.decoder = framing.Decoder()
        self.app_state = P.AppState.BOOTING
        self.last_heartbeat: float | None = None
        self.fw_state: int | None = None
        self._pending_acks: dict[int, float] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._reader, name="uart-reader", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    # ---- sending -------------------------------------------------------------

    def _write(self, frame: bytes) -> None:
        with self._lock:
            self.port.write(frame)

    def send(self, msg_id: int, **fields) -> None:
        self._write(framing.encode(msg_id, **fields))

    def send_state(self, app_state: int) -> None:
        """Announce an application state change (CAL_STATE)."""
        self.app_state = app_state
        self.send(P.MSG_CAL_STATE, app_state=app_state)

    def send_ready(self, rms_before: float, rms_after: float, reduction_pct: float) -> None:
        self.send(P.MSG_READY, rms_before_x10=min(65535, int(round(rms_before * 10))),
                  rms_after_x10=min(65535, int(round(rms_after * 10))),
                  reduction_pct=max(0, min(255, int(round(reduction_pct)))))

    def send_cal_error(self, error_code: int) -> None:
        self.send(P.MSG_CAL_ERROR, error_code=error_code)

    # ---- receiving -----------------------------------------------------------

    def process(self, data: bytes) -> list[framing.Message]:
        """Decode bytes and apply link-level behaviour. Returns application messages."""
        delivered = []
        for msg in self.decoder.feed(data):
            if msg.id == P.MSG_HEARTBEAT:
                self.last_heartbeat = self.clock()
                self.fw_state = msg.fw_state
                self.send(P.MSG_HEARTBEAT_REPLY, app_state=self.app_state)
            elif msg.id == P.MSG_ACK:
                self._pending_acks.pop(msg.acked_id, None)
                continue
            elif msg.id in REQUESTS_NEEDING_ACK:
                self.send(P.MSG_ACK, acked_id=msg.id)
            delivered.append(msg)
            if self.on_message:
                try:
                    self.on_message(msg)
                except Exception:          # a handler bug must not kill the reader
                    log.exception("message handler failed for %s", msg.name)
        return delivered

    def _reader(self) -> None:
        while not self._stop.is_set():
            try:
                data = self.port.read(64)
            except Exception as exc:
                log.error("serial read failed: %s", exc)
                time.sleep(0.5)
                continue
            if data:
                self.process(data)

    # ---- health ----------------------------------------------------------------

    @property
    def link_up(self) -> bool:
        if self.last_heartbeat is None:
            return False
        return (self.clock() - self.last_heartbeat) * 1000.0 < P.LINK_DOWN_MS

    def status_text(self) -> str:
        if not self.link_up:
            return "controller offline"
        return "controller " + P.FwState.NAMES.get(self.fw_state, "?").lower().replace("_", " ")


class LoopbackPort:
    """In-memory port: what one side writes, the other side reads. For tests."""

    def __init__(self):
        self._a_to_b = bytearray()
        self._b_to_a = bytearray()
        self.timeout = 0.0

    def side(self, name: str):
        parent = self

        class _Side:
            timeout = 0.0

            def write(self, data: bytes):
                (parent._a_to_b if name == "a" else parent._b_to_a).extend(data)

            def read(self, n: int) -> bytes:
                buf = parent._b_to_a if name == "a" else parent._a_to_b
                out = bytes(buf[:n])
                del buf[:n]
                return out
        return _Side()
