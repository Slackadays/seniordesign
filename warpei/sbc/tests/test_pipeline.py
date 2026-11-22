"""Tasks 4.3 and 4.5: capture policy, source detection, pipeline modes."""

from __future__ import annotations

import numpy as np
import pytest

from warpei.calibration import pattern
from warpei.config import Config
from warpei.video import pipeline
from warpei.video.capture import Capture

PANEL = (pattern.PANEL_WIDTH, pattern.PANEL_HEIGHT)


class FakeClock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


class FakeRenderer:
    """Records what was rendered and which model/flip were set."""
    class _Warp:
        def __init__(self): self.model = "unset"; self.flip = None
        def set_model(self, m): self.model = m
        def set_flip(self, f): self.flip = f
    def __init__(self):
        self.warp = self._Warp(); self.frames = []
    def render(self, rgb): self.frames.append(rgb)


def frame(v=100):
    return np.full((1080, 1920, 3), v, np.uint8)


def test_latest_frame_policy_drops_not_queues():
    clock = FakeClock()
    cap = Capture(cap=None, no_source_seconds=2.0, clock=clock)
    for v in (1, 2, 3):
        cap.push(frame(v))
    got = cap.latest()
    assert got[0, 0, 0] == 3
    assert cap.stats.frames == 3 and cap.stats.delivered == 1 and cap.stats.dropped == 2
    assert cap.latest() is got and cap.stats.delivered == 1      # same frame, not counted twice


def test_no_source_after_timeout():
    clock = FakeClock()
    cap = Capture(cap=None, no_source_seconds=2.0, clock=clock)
    assert cap.latest() is None and not cap.has_source
    cap.push(frame())
    assert cap.has_source
    clock.t += 1.9
    assert cap.latest() is not None
    clock.t += 0.2
    assert cap.latest() is None and not cap.has_source
    cap.push(frame())
    assert cap.has_source


def test_pipeline_modes():
    cfg = Config(source_rotation=90)
    clock = FakeClock()
    cap = Capture(cap=None, no_source_seconds=2.0, clock=clock)
    r = FakeRenderer()
    p = pipeline.Pipeline(cfg, cap, r, status_lines=lambda: ["no video input"])
    assert p.step() == "no_source"
    assert r.frames[-1].shape == (PANEL[1], PANEL[0], 3) and r.warp.model is None

    cap.push(frame(200))
    assert p.step() == "passthrough"
    assert r.frames[-1].shape == (PANEL[1], PANEL[0], 3) and r.frames[-1].mean() > 190

    class M:                    # stand-in model object
        panel_size = PANEL
    p.set_model(M())
    assert p.step() == "warped" and r.warp.model is not None
    assert p.times.n == 3 and set(p.times.row()) == {"capture_wait", "prepare", "render", "total"}


def test_prepare_rotates_1080p_to_panel_and_keeps_rgb():
    cfg = Config(source_rotation=90)
    cap = Capture(cap=None)
    p = pipeline.Pipeline(cfg, cap, FakeRenderer())
    bgr = np.zeros((1080, 1920, 3), np.uint8); bgr[..., 2] = 255       # red in BGR
    rgb = p.prepare(bgr)
    assert rgb.shape == (PANEL[1], PANEL[0], 3) and rgb[0, 0].tolist() == [255, 0, 0]


def test_flip_goes_to_shader_not_cpu():
    cfg = Config(source_flip_horizontal=True)
    r = FakeRenderer()
    pipeline.Pipeline(cfg, Capture(cap=None), r)
    assert r.warp.flip is True


def test_status_card_size():
    card = pipeline.status_card(PANEL, ["controller offline", "no video input"])
    assert card.shape == (PANEL[1], PANEL[0], 3)
