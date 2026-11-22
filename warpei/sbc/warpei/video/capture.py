"""HDMI capture (task 4.3, Report 7.4).

A capture thread reads frames from the USB capture dongle (or any V4L2 /
UVC source) and keeps only the latest one, so the render loop never waits
on the camera and never falls behind: if rendering is slower than capture,
frames are dropped, not queued. Report 7.4 drops every other frame of a
60 fps source to hold 30 fps; that is what a latest-frame policy does.

Source presence: if no frame arrives for `no_source_seconds` the capture
reports no source and the application shows the status card.
"""

from __future__ import annotations

import logging
import platform
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

log = logging.getLogger("warpei.capture")


@dataclass
class CaptureStats:
    frames: int = 0            # frames read from the device
    delivered: int = 0         # frames handed to the renderer
    dropped: int = 0           # frames replaced before anyone read them
    last_frame_at: float = 0.0
    fps: float = 0.0


def open_source(source: str, width: int, height: int, mjpeg: bool = True) -> cv2.VideoCapture:
    """Open a capture device by index or a file path, requesting the given size."""
    if source.isdigit():
        index = int(source)
        cap = cv2.VideoCapture(index, cv2.CAP_V4L2) if platform.system() == "Linux" else cv2.VideoCapture(index)
        if mjpeg:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)        # one buffer: lowest latency where supported
    else:
        cap = cv2.VideoCapture(source)
    return cap


class Capture:
    """Latest-frame capture thread around any object with read() -> (ok, frame)."""

    def __init__(self, cap, no_source_seconds: float = 2.0, clock=time.monotonic):
        self.cap = cap
        self.no_source_seconds = no_source_seconds
        self.clock = clock
        self.stats = CaptureStats()
        self._latest: np.ndarray | None = None
        self._latest_seq = 0
        self._taken_seq = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fps_t0 = clock()
        self._fps_n = 0

    # ---- lifecycle ---------------------------------------------------------

    def start(self) -> "Capture":
        self._thread = threading.Thread(target=self._loop, name="capture", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        try:
            self.cap.release()
        except Exception:
            pass

    # ---- thread ------------------------------------------------------------

    def push(self, frame: np.ndarray) -> None:
        """Store a frame as the latest. Called by the thread; tests call it directly."""
        now = self.clock()
        with self._lock:
            if self._latest is not None and self._latest_seq != self._taken_seq:
                self.stats.dropped += 1
            self._latest = frame
            self._latest_seq += 1
            self.stats.frames += 1
            self.stats.last_frame_at = now
        self._fps_n += 1
        if now - self._fps_t0 >= 1.0:
            self.stats.fps = self._fps_n / (now - self._fps_t0)
            self._fps_t0, self._fps_n = now, 0

    def _loop(self) -> None:
        while not self._stop.is_set():
            ok, frame = self.cap.read()
            if not ok or frame is None:
                time.sleep(0.05)            # no signal: poll gently
                continue
            self.push(frame)

    # ---- consumer ------------------------------------------------------------

    def latest(self) -> np.ndarray | None:
        """The newest frame, or None if there is none or it is stale (no source)."""
        with self._lock:
            if self._latest is None:
                return None
            if self.clock() - self.stats.last_frame_at > self.no_source_seconds:
                return None
            if self._latest_seq != self._taken_seq:
                self._taken_seq = self._latest_seq
                self.stats.delivered += 1
            return self._latest

    @property
    def has_source(self) -> bool:
        with self._lock:
            return (self._latest is not None
                    and self.clock() - self.stats.last_frame_at <= self.no_source_seconds)
