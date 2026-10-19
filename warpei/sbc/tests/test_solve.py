"""Task 1.4: warp solver.

Acceptance: points generated from a known model are reproduced within
0.1 pixel; a solve takes under 1 s; the end-to-end simulated pipeline
(detect -> undistort -> solve) reproduces the true surface map closely.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from conftest import sim_camera, surface_map
from warpei.calibration import pattern
from warpei.calibration.detect import detect_grid
from warpei.calibration.solve import WarpModel, fit_similarity, footprint_polygon, solve_warp

PANEL = (pattern.PANEL_WIDTH, pattern.PANEL_HEIGHT)


def known_model() -> WarpModel:
    H = np.array([[180.0, 8.0, 960.0], [5.0, 320.0, 540.0], [0.02, 0.01, 1.0]])
    return WarpModel(PANEL, H, np.array([3.0, 1.0, -2.0, 6.0, 0.5, -4.0]),
                     np.array([-1.0, 0.5, 2.0, 3.0, -1.5, 5.0]), 0.18, np.array([700.0, 100.0]))


def test_recovers_known_model_within_tenth_pixel():
    truth = known_model()
    panel_pts = pattern.grid_points()
    camera_pts = truth.forward(panel_pts)
    model = solve_warp(panel_pts, camera_pts)
    check = pattern.grid_points(offset=(0.5, 0.5))     # points not used in the fit
    assert np.abs(model.forward(check) - truth.forward(check)).max() < 0.1
    assert model.fit_rms < 0.05


def test_pure_homography_leaves_polynomial_near_zero():
    truth = known_model()
    truth.coeff_u[:] = 0
    truth.coeff_v[:] = 0
    panel_pts = pattern.grid_points()
    model = solve_warp(panel_pts, truth.forward(panel_pts))
    assert np.abs(model.coeff_u).max() < 1e-3
    assert np.abs(model.coeff_v).max() < 1e-3
    assert model.homography_rms < 1e-3


def test_solve_is_fast():
    panel_pts = pattern.grid_points()
    camera_pts = known_model().forward(panel_pts)
    start = time.perf_counter()
    for _ in range(10):
        solve_warp(panel_pts, camera_pts)
    assert (time.perf_counter() - start) / 10 < 1.0


def test_end_to_end_simulation():
    """detect -> undistort -> solve on a simulated curved surface."""
    view = sim_camera(scale=0.17, bow=1.0, blur=2.0)
    result = detect_grid(view.image)
    assert result.found
    undistorted = view.camera.undistort_points(result.centers)
    model = solve_warp(view.panel_points, undistorted)

    # The fitted map should predict held-out points close to the true surface map.
    check = pattern.grid_points(offset=(0.5, 0.5))
    truth = surface_map(check, view.homography, view.bow)
    err = np.sqrt(np.sum((model.forward(check) - truth) ** 2, axis=1))
    print(f"\nsimulated fit rms {model.fit_rms:.3f} px, held-out rms {np.sqrt(np.mean(err**2)):.3f} px")
    assert np.sqrt(np.mean(err ** 2)) < 1.0
    assert model.homography_rms > model.fit_rms      # the polynomial improved on the homography


def test_target_rectangle_inside_footprint():
    truth = known_model()
    panel_pts = pattern.grid_points()
    model = solve_warp(panel_pts, truth.forward(panel_pts))
    assert 0.0 <= model.shrink < 0.5
    # The whole source image must land inside the region the projector can
    # light: all four source corners, mapped by T, lie inside the footprint.
    import cv2
    w, h = PANEL
    corners = np.array([[0, 0], [w, 0], [w, h], [0, h]], float)
    poly = footprint_polygon(model).reshape(-1, 1, 2)
    for x, y in model.target(corners):
        assert cv2.pointPolygonTest(poly, (float(x), float(y)), False) >= 0
    # And the centre of the panel shows a source pixel near the source centre.
    centre_src = model.source_lookup(np.array([[w / 2, h / 2]]))[0]
    assert 0 < centre_src[0] < w and 0 < centre_src[1] < h


def test_fit_similarity():
    p = pattern.grid_points().astype(np.float64)
    scale, offset = fit_similarity(p, 0.2 * p + np.array([300.0, 40.0]))
    assert abs(scale - 0.2) < 1e-9
    assert np.allclose(offset, [300.0, 40.0])


def test_dict_round_trip():
    model = known_model()
    model.fit_rms, model.shrink = 0.4, 0.07
    back = WarpModel.from_dict(model.to_dict())
    assert np.allclose(back.homography, model.homography)
    assert np.allclose(back.coeff_u, model.coeff_u)
    assert back.target_scale == model.target_scale
    assert back.fit_rms == 0.4


def test_rejects_bad_input():
    p = pattern.grid_points()
    with pytest.raises(ValueError):
        solve_warp(p, p[:-1])
    with pytest.raises(ValueError):
        solve_warp(p[:5], p[:5])
    bad = p.copy().astype(float)
    bad[0, 0] = np.nan
    with pytest.raises(ValueError):
        solve_warp(p, bad)
