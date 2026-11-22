"""Application wiring: UART events drive calibration, flip, and state reports."""

from __future__ import annotations

import numpy as np

from conftest import sim_camera, make_camera_calibration
from warpei import main as app_main
from warpei.config import Config
from warpei.link import framing, protocol as P
from warpei.link.uart import LoopbackPort, UartLink
from warpei.video.capture import Capture
from test_app import FakeRig
from test_pipeline import FakeRenderer


class RigCamera:
    """Camera callable that photographs whatever the renderer last drew."""
    def __init__(self, renderer, rig):
        self.renderer, self.rig = renderer, rig
    def __call__(self):
        rgb = self.renderer.frames[-1]
        import cv2
        self.rig.shown.append(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        return self.rig.capture()


def make_app(tmp_path, with_link=True):
    cfg = Config(calibration_path=str(tmp_path / "calibration.json"), camera_file=str(tmp_path / "none.json"),
                 settle_seconds=0.0, camera_warmup_frames=0, detect_retries=0)
    renderer = FakeRenderer()
    rig = FakeRig()
    camera = RigCamera(renderer, rig)
    lp = LoopbackPort()
    link = UartLink(lp.side("a")) if with_link else None
    app = app_main.Application(cfg, renderer, Capture(cap=None), camera, link)
    app.calibrator.camera = rig.camera          # use the simulated lens model
    app.calibrator.sleep = lambda s: None
    if link:
        link.on_message = app.on_message
    return app, link, lp.side("b"), renderer


def esp_messages(esp):
    return framing.Decoder().feed(esp.read(4096))


def test_boot_state_no_source(tmp_path):
    app, link, esp, _ = make_app(tmp_path)
    assert app.app_state == P.AppState.NO_SOURCE
    assert esp_messages(esp)[-1].app_state == P.AppState.NO_SOURCE


def test_cal_start_runs_calibration_and_reports_ready(tmp_path):
    app, link, esp, renderer = make_app(tmp_path)
    esp.read(4096)
    esp.write(framing.encode(P.MSG_CAL_START))
    link.process(link.port.read(64))
    assert app._cal_request.is_set()
    app.run_calibration()
    msgs = esp_messages(esp)
    names = [m.name for m in msgs]
    assert "ACK" in names and "READY" in names
    ready = next(m for m in msgs if m.name == "READY")
    assert ready.reduction_pct >= 50
    assert app.pipeline.model is not None
    assert msgs[-1].name == "CAL_STATE" and msgs[-1].app_state == P.AppState.NO_SOURCE   # no HDMI in the test


def test_calibration_failure_reports_error_code(tmp_path):
    app, link, esp, renderer = make_app(tmp_path)
    app.calibrator.capture = lambda: np.full((1080, 1920, 3), 80, np.uint8)     # camera never sees the grid
    app.run_calibration()
    msgs = esp_messages(esp)
    err = next(m for m in msgs if m.name == "CAL_ERROR")
    assert err.error_code == P.CalError.DETECT_FAIL
    assert app.app_state == P.AppState.ERROR


def test_flip_message_updates_shader_and_calibrator(tmp_path):
    app, link, esp, renderer = make_app(tmp_path)
    esp.write(framing.encode(P.MSG_FLIP, flip=1))
    link.process(link.port.read(64))
    assert renderer.warp.flip is True and app.calibrator.flip is True


def test_error_code_mapping():
    assert app_main.error_code_for("ACCURACY: reduction 12%") == P.CalError.ACCURACY
    assert app_main.error_code_for("TIMEOUT: took 200 s") == P.CalError.TIMEOUT
    assert app_main.error_code_for("camera returned no frame") == P.CalError.CAMERA


def test_runs_without_link(tmp_path):
    app, link, esp, renderer = make_app(tmp_path, with_link=False)
    app.run_calibration()
    assert app.pipeline.model is not None
