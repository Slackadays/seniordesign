"""Task 1.5: error measurement.

Acceptance: a hand-computed 4-point case gives the expected RMS; the shifted
verify grid still detects; a simulated correction cuts the error by 50%.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from conftest import sim_camera
from warpei.calibration import pattern, validate
from warpei.calibration.detect import detect_grid
from warpei.calibration.solve import solve_warp


def test_hand_computed_four_points():
    detected = np.array([[0, 0], [3, 4], [10, 10], [10, 11]], float)
    expected = np.array([[0, 0], [0, 0], [10, 10], [10, 10]], float)
    # distances: 0, 5, 0, 1 -> mean of squares = 26/4 = 6.5 -> rms = 2.5495
    report = validate.rms_error(detected, expected)
    assert report.rms == pytest.approx(np.sqrt(6.5))
    assert report.mean == pytest.approx(1.5)
    assert report.max == pytest.approx(5.0)
    assert report.count == 4


def test_percent_reduction():
    before = validate.rms_error([[0, 0]], [[10, 0]])
    after = validate.rms_error([[0, 0]], [[4, 0]])
    assert validate.percent_reduction(before, after) == pytest.approx(60.0)
    assert validate.meets_specification(before, after)
    worse = validate.rms_error([[0, 0]], [[6, 0]])
    assert not validate.meets_specification(before, worse)


def test_mismatched_sizes_rejected():
    with pytest.raises(ValueError):
        validate.rms_error(np.zeros((3, 2)), np.zeros((4, 2)))


def test_verify_grid_renders_and_detects():
    image = pattern.render_pattern(offset=pattern.VERIFY_OFFSET)
    result = detect_grid(image)
    assert result.found
    assert np.abs(result.centers - pattern.grid_points(offset=pattern.VERIFY_OFFSET)).max() < 1.0


def test_simulated_correction_halves_the_error():
    """Full loop: calibrate on the grid, pre-warp the shifted grid, re-photograph, score."""
    view = sim_camera(scale=0.17, bow=1.5, blur=1.5)
    result = detect_grid(view.image)
    assert result.found
    undist = view.camera.undistort_points(result.centers)
    model = solve_warp(view.panel_points, undist)

    # "Before": raw projection of the shifted grid.
    shifted = pattern.grid_points(offset=pattern.VERIFY_OFFSET)
    raw = sim_camera(scale=0.17, bow=1.5, blur=1.5, offset=pattern.VERIFY_OFFSET, seed=7)
    raw_pts = view.camera.undistort_points(detect_grid(raw.image).centers)
    before = validate.uncorrected_error(model, shifted, raw_pts)

    # "After": pre-warp the shifted pattern with the model (CPU remap), then photograph it.
    w, h = model.panel_size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    src = model.source_lookup(np.stack([xx.ravel(), yy.ravel()], axis=1))
    map_x = src[:, 0].reshape(h, w)
    map_y = src[:, 1].reshape(h, w)
    source = pattern.render_pattern(offset=pattern.VERIFY_OFFSET)
    prewarped = cv2.remap(source, map_x, map_y, cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=255)
    corrected = sim_camera(scale=0.17, bow=1.5, blur=1.5, seed=8, panel_image=prewarped)
    det = detect_grid(corrected.image)
    assert det.found
    after = validate.corrected_error(model, shifted, view.camera.undistort_points(det.centers))

    print("\n" + validate.summary(before, after))
    assert validate.meets_specification(before, after)
    assert after.rms < 2.0
