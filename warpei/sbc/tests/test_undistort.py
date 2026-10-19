"""Task 1.3: lens distortion correction.

Acceptance: synthetic points bent by a known distortion come back within
0.1 pixel after undistortion.
"""

from __future__ import annotations

import numpy as np
import pytest

from conftest import make_camera_calibration
from warpei.calibration.undistort import CameraCalibration, identity_calibration


def grid(w=1920, h=1080, n=15):
    xs = np.linspace(0.1 * w, 0.9 * w, n)
    ys = np.linspace(0.1 * h, 0.9 * h, n)
    return np.array([(x, y) for y in ys for x in xs], np.float32)


def test_round_trip_within_tenth_pixel():
    cam = make_camera_calibration()
    ideal = grid()
    bent = cam.distort_points(ideal)
    assert np.abs(bent - ideal).max() > 5.0          # the distortion is not trivial
    back = cam.undistort_points(bent)
    assert np.abs(back - ideal).max() < 0.1


def test_strong_distortion_still_round_trips():
    cam = make_camera_calibration(k1=-0.25, k2=0.08, p1=0.002, p2=0.001)
    ideal = grid()
    assert np.abs(cam.undistort_points(cam.distort_points(ideal)) - ideal).max() < 0.1


def test_identity_calibration_changes_nothing():
    cam = identity_calibration(1920, 1080)
    pts = grid()
    assert np.abs(cam.undistort_points(pts) - pts).max() < 1e-4


def test_json_round_trip(tmp_path):
    cam = make_camera_calibration()
    cam.rms_reprojection_error = 0.31
    cam.per_view_errors = [0.2, 0.4]
    cam.source_images = ["a.png", "b.png"]
    path = tmp_path / "camera.json"
    cam.save(path)
    loaded = CameraCalibration.load(path)
    assert np.allclose(loaded.camera_matrix, cam.camera_matrix)
    assert np.allclose(loaded.dist_coeffs, cam.dist_coeffs)
    assert loaded.image_size == cam.image_size
    assert loaded.rms_reprojection_error == 0.31
    assert loaded.per_view_errors == [0.2, 0.4]


def test_image_size_mismatch_is_rejected():
    cam = make_camera_calibration()
    cam.check_image_size(1920, 1080)
    with pytest.raises(ValueError):
        cam.check_image_size(1280, 720)
