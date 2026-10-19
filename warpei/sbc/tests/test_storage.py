"""Task 1.6: calibration storage.

Acceptance: save then load returns identical values; a failure during the
write leaves the previous file readable.
"""

from __future__ import annotations

import json
import os

import numpy as np
import pytest

from conftest import make_camera_calibration
from warpei import storage
from warpei.calibration import pattern
from warpei.calibration.solve import solve_warp


def make_calibration() -> storage.CalibrationFile:
    H = np.array([[180.0, 8.0, 960.0], [5.0, 320.0, 540.0], [0.02, 0.01, 1.0]])
    p = pattern.grid_points()
    c = (np.c_[p, np.ones(len(p))] @ H.T)
    c = c[:, :2] / c[:, 2:]
    warp = solve_warp(p, c)
    return storage.CalibrationFile(warp=warp, camera=make_camera_calibration(),
                                   rms_before=12.5, rms_after=3.1, notes={"surface": "curved"})


def test_save_then_load_is_identical(tmp_path):
    calib = make_calibration()
    path = tmp_path / "calibration.json"
    storage.save(calib, path)
    loaded = storage.load(path)

    assert np.array_equal(loaded.warp.homography, calib.warp.homography)
    assert np.array_equal(loaded.warp.coeff_u, calib.warp.coeff_u)
    assert np.array_equal(loaded.warp.coeff_v, calib.warp.coeff_v)
    assert loaded.warp.target_scale == calib.warp.target_scale
    assert np.array_equal(loaded.warp.target_offset, calib.warp.target_offset)
    assert np.array_equal(loaded.camera.camera_matrix, calib.camera.camera_matrix)
    assert np.array_equal(loaded.camera.dist_coeffs, calib.camera.dist_coeffs)
    assert loaded.rms_before == 12.5 and loaded.rms_after == 3.1
    assert loaded.notes == {"surface": "curved"}
    assert loaded.saved_at != ""
    assert not list(tmp_path.glob("*.tmp"))          # no temp file left behind


def test_failed_write_keeps_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "calibration.json"
    first = make_calibration()
    first.rms_after = 1.0
    storage.save(first, path)

    def crash(*args, **kwargs):
        raise OSError("simulated power cut")
    monkeypatch.setattr(storage.os, "replace", crash)

    second = make_calibration()
    second.rms_after = 2.0
    with pytest.raises(OSError):
        storage.save(second, path)

    assert storage.load(path).rms_after == 1.0        # old file intact
    assert not list(tmp_path.glob("*.tmp"))          # temp file cleaned up


def test_load_or_none_on_missing_or_corrupt(tmp_path):
    assert storage.load_or_none(tmp_path / "missing.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert storage.load_or_none(bad) is None
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"format_version": 99}), encoding="utf-8")
    assert storage.load_or_none(wrong) is None


def test_file_is_human_readable(tmp_path):
    path = tmp_path / "calibration.json"
    storage.save(make_calibration(), path)
    data = json.loads(path.read_text())
    assert len(data["warp"]["coeff_u"]) == 6
    assert len(data["camera"]["dist_coeffs"]) == 5
