"""Tasks 2.3 and 2.4: the calibration state machine and verify step.

The Calibrator is driven by a fake display and a fake camera: whatever the
app displays is rendered through the simulated optical path and handed
back as the next camera frame. That closes the loop with no hardware.

Acceptance: one call ends in a corrected image; the sequence finishes well
under 180 s; a failed detection retries, then falls back to the last saved
calibration; the verify RMS falls by at least 50%.
"""

from __future__ import annotations

import numpy as np
import pytest

from conftest import sim_camera, make_camera_calibration
from warpei import storage
from warpei.app import Calibrator, State
from warpei.config import Config


class FakeRig:
    """Display + camera pair wired through the simulator."""

    def __init__(self, bow=1.0, blur=1.5, fail_frames=0, blank_after=None):
        self.bow, self.blur = bow, blur
        self.shown: list[np.ndarray] = []
        self.frames = 0
        self.fail_frames = fail_frames        # first N captures return a blank frame
        self.blank_after = blank_after        # all captures after N are blank
        self.camera = make_camera_calibration()

    def display(self, image):
        self.shown.append(image)

    def capture(self):
        self.frames += 1
        blank = np.full((1080, 1920, 3), 80, np.uint8)
        if self.frames <= self.fail_frames:
            return blank
        if self.blank_after is not None and self.frames > self.blank_after:
            return blank
        panel = self.shown[-1]
        if panel.ndim == 3:
            import cv2
            panel = cv2.cvtColor(panel, cv2.COLOR_BGR2GRAY)
        return sim_camera(bow=self.bow, blur=self.blur, seed=self.frames, panel_image=panel).image


def make_config(tmp_path, **kw) -> Config:
    return Config(calibration_path=str(tmp_path / "calibration.json"),
                  settle_seconds=0.0, camera_warmup_frames=0, **kw)


def test_full_sequence_passes(tmp_path):
    rig = FakeRig()
    cfg = make_config(tmp_path)
    states = []
    cal = Calibrator(cfg, rig.display, rig.capture, rig.camera, sleep=lambda s: None)
    cal.on_state_change(states.append)

    run = cal.calibrate()
    print("\n" + run.summary())
    assert run.error == ""
    assert run.passed and run.reduction_percent >= 50
    assert run.rms_after < 2.0
    assert run.seconds < 30
    assert cal.state == State.RUN
    assert states == [State.PROJECT_PATTERN, State.CAPTURE, State.SOLVE, State.VERIFY, State.RUN]
    assert run.attempts == {"fit grid": 1, "verify raw": 1, "verify corrected": 1}

    saved = storage.load(cfg.calibration_path)
    assert saved.rms_after == pytest.approx(run.rms_after)
    assert saved.notes["passed"] is True


def test_retry_then_success(tmp_path):
    rig = FakeRig(fail_frames=2)               # first two captures are blank
    cfg = make_config(tmp_path, detect_retries=3)
    cal = Calibrator(cfg, rig.display, rig.capture, rig.camera, sleep=lambda s: None)
    run = cal.calibrate()
    assert run.error == ""
    assert run.attempts["fit grid"] == 3
    assert cal.state == State.RUN


def test_failure_without_saved_calibration(tmp_path):
    rig = FakeRig(blank_after=0)               # camera never sees the grid
    cfg = make_config(tmp_path, detect_retries=1)
    cal = Calibrator(cfg, rig.display, rig.capture, rig.camera, sleep=lambda s: None)
    run = cal.calibrate()
    assert "not found" in run.error
    assert cal.state == State.FAILED
    assert cal.model is None
    assert not (tmp_path / "calibration.json").exists()


def test_failure_falls_back_to_saved(tmp_path):
    cfg = make_config(tmp_path, detect_retries=1)
    good = FakeRig()
    cal = Calibrator(cfg, good.display, good.capture, good.camera, sleep=lambda s: None)
    assert cal.calibrate().passed
    first_model = cal.model

    # New process: loads from disk, then a calibration fails mid-way.
    bad = FakeRig(blank_after=1)               # fit grid ok, verify raw fails
    cal2 = Calibrator(cfg, bad.display, bad.capture, bad.camera, sleep=lambda s: None)
    assert cal2.load_saved()
    assert cal2.state == State.RUN
    run = cal2.calibrate()
    assert run.error != ""
    assert cal2.state == State.RUN             # fell back
    assert np.allclose(cal2.model.coeff_u, first_model.coeff_u)
    assert storage.load(cfg.calibration_path).rms_after == pytest.approx(cal.last_run.rms_after)


def test_load_saved_rejects_other_panel(tmp_path):
    cfg = make_config(tmp_path)
    rig = FakeRig()
    Calibrator(cfg, rig.display, rig.capture, rig.camera, sleep=lambda s: None).calibrate()
    other = Config(calibration_path=cfg.calibration_path, panel_width=1080, panel_height=1920)
    cal = Calibrator(other, rig.display, rig.capture, rig.camera)
    assert not cal.load_saved()
    assert cal.state == State.IDLE


def test_timeout_is_reported(tmp_path):
    rig = FakeRig()
    cfg = make_config(tmp_path, calibration_timeout_seconds=0.0001)
    cal = Calibrator(cfg, rig.display, rig.capture, rig.camera, sleep=lambda s: None)
    run = cal.calibrate()
    assert "over the" in run.error
