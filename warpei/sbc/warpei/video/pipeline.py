"""Video pipeline (Report 7.4): capture thread -> prepare -> GPU warp -> panel.

Modes, chosen each frame:
  no source    -> status card (panel-sized image drawn with OpenCV)
  passthrough  -> source shown unwarped (no calibration loaded)
  warped       -> source through the warp shader

The renderer is any object with .warp (a GLWarp) and .render(rgb). The
pipeline owns no threads of its own; run() is the application's main loop
and returns when `should_stop()` says so.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

import cv2
import numpy as np

from ..calibration.solve import WarpModel
from ..config import Config
from . import reference
from .capture import Capture

log = logging.getLogger("warpei.pipeline")


@dataclass
class StageTimes:
    """Running mean and worst case per stage, in milliseconds."""
    n: int = 0
    sums: dict = field(default_factory=dict)
    worst: dict = field(default_factory=dict)

    def add(self, stage: str, ms: float) -> None:
        self.sums[stage] = self.sums.get(stage, 0.0) + ms
        self.worst[stage] = max(self.worst.get(stage, 0.0), ms)

    def row(self) -> dict:
        return {s: (self.sums[s] / max(1, self.n), self.worst[s]) for s in self.sums}


def status_card(panel_size: tuple[int, int], lines: list[str]) -> np.ndarray:
    """Panel-sized card shown when there is no video source (Report 7.4, 7.6)."""
    w, h = panel_size
    img = np.full((h, w, 3), 24, np.uint8)
    cv2.rectangle(img, (40, 40), (w - 40, h - 40), (90, 90, 90), 4)
    scale = max(1.0, w / 900)
    y = int(h * 0.3)
    cv2.putText(img, "WARPEI", (int(w * 0.1), y), cv2.FONT_HERSHEY_SIMPLEX, 2.2 * scale, (255, 255, 255), int(4 * scale), cv2.LINE_AA)
    y += int(90 * scale)
    for line in lines:
        cv2.putText(img, line, (int(w * 0.1), y), cv2.FONT_HERSHEY_SIMPLEX, 1.1 * scale, (200, 200, 200), int(2 * scale), cv2.LINE_AA)
        y += int(60 * scale)
    return img


class Pipeline:
    def __init__(self, config: Config, capture: Capture, renderer,
                 status_lines: Callable[[], list[str]] = lambda: []):
        self.config = config
        self.capture = capture
        self.renderer = renderer
        self.status_lines = status_lines
        self.model: WarpModel | None = None
        self.flip = bool(config.source_flip_horizontal)
        self.paused = False               # true while the calibrator owns the display
        self.times = StageTimes()
        self.mode = "no_source"
        self._last_card_at = 0.0
        self._card: np.ndarray | None = None
        self.renderer.warp.set_model(None)
        self.renderer.warp.set_flip(self.flip)

    # ---- state ---------------------------------------------------------------

    def set_model(self, model: WarpModel | None) -> None:
        self.model = model
        self.renderer.warp.set_model(model)

    def set_flip(self, flip: bool) -> None:
        self.flip = bool(flip)
        self.renderer.warp.set_flip(self.flip)

    # ---- one frame -------------------------------------------------------------

    def prepare(self, frame_bgr: np.ndarray) -> np.ndarray:
        """Rotate and scale the source to the panel; return RGB."""
        cfg = self.config
        panel = reference.prepare_source(frame_bgr, cfg.panel_size, cfg.source_rotation,
                                         False, cfg.source_flip_vertical)   # horizontal flip is in the shader
        return cv2.cvtColor(panel, cv2.COLOR_BGR2RGB)

    def step(self) -> str:
        """Render one frame. Returns the mode used."""
        t0 = time.perf_counter()
        frame = self.capture.latest()
        t1 = time.perf_counter()
        if frame is None:
            self.mode = "no_source"
            now = time.perf_counter()
            if self._card is None or now - self._last_card_at > 1.0:
                self._card = cv2.cvtColor(status_card(self.config.panel_size, self.status_lines()), cv2.COLOR_BGR2RGB)
                self._last_card_at = now
            rgb = self._card
            self.renderer.warp.set_model(None)
        else:
            self.mode = "warped" if self.model is not None else "passthrough"
            rgb = self.prepare(frame)
            if self.model is not None:
                self.renderer.warp.set_model(self.model)
        t2 = time.perf_counter()
        self.renderer.render(rgb)
        t3 = time.perf_counter()
        self.times.n += 1
        self.times.add("capture_wait", (t1 - t0) * 1000)
        self.times.add("prepare", (t2 - t1) * 1000)
        self.times.add("render", (t3 - t2) * 1000)
        self.times.add("total", (t3 - t0) * 1000)
        return self.mode

    def run(self, should_stop: Callable[[], bool], max_fps: float = 60.0) -> None:
        period = 1.0 / max_fps
        while not should_stop():
            if self.paused:
                time.sleep(0.05)
                continue
            start = time.perf_counter()
            self.step()
            if hasattr(self.renderer, "poll_quit") and self.renderer.poll_quit():
                break
            spare = period - (time.perf_counter() - start)
            if spare > 0:
                time.sleep(spare)
