"""Task 2.1: CPU reference warp.

Acceptance: in simulation, the grid warped through the model lands within
1 camera pixel of its target positions; the time to warp one 1440 x 2560
frame is recorded.
"""

from __future__ import annotations

import time

import cv2
import numpy as np

from conftest import sim_camera
from warpei.calibration import pattern
from warpei.calibration.detect import detect_grid
from warpei.calibration.solve import solve_warp
from warpei.video import reference

PANEL = (pattern.PANEL_WIDTH, pattern.PANEL_HEIGHT)


def test_warped_grid_lands_on_target():
    view = sim_camera(scale=0.17, bow=1.0, blur=1.5)
    det = detect_grid(view.image)
    model = solve_warp(view.panel_points, view.camera.undistort_points(det.centers))

    maps = reference.build_maps(model)
    warped = reference.warp_image(pattern.render_pattern(offset=pattern.VERIFY_OFFSET), maps)
    seen = sim_camera(scale=0.17, bow=1.0, blur=1.5, seed=9, panel_image=warped)
    det2 = detect_grid(seen.image)
    assert det2.found
    target = model.target(pattern.grid_points(offset=pattern.VERIFY_OFFSET))
    err = np.sqrt(np.sum((view.camera.undistort_points(det2.centers) - target) ** 2, axis=1))
    assert err.max() < 1.0


def test_build_and_warp_timing():
    view = sim_camera(bow=0.5, blur=1.0)
    det = detect_grid(view.image)
    model = solve_warp(view.panel_points, view.camera.undistort_points(det.centers))
    maps = reference.build_maps(model)
    source = reference.test_card(PANEL)
    reference.warp_image(source, maps)                  # warm up
    start = time.perf_counter()
    for _ in range(5):
        reference.warp_image(source, maps)
    per_frame = (time.perf_counter() - start) / 5
    print(f"\nmap build {maps.build_seconds:.2f} s, remap {per_frame * 1000:.1f} ms per 1440x2560 frame")
    assert maps.build_seconds < 10.0
    assert per_frame < 1.0


def test_outside_lookup_is_black():
    model = solve_warp(pattern.grid_points(), pattern.grid_points() * 0.5 + 100)
    maps = reference.build_maps(model)
    out = reference.warp_image(np.full((PANEL[1], PANEL[0], 3), 200, np.uint8), maps)
    assert out.shape == (PANEL[1], PANEL[0], 3)
    assert out.min() == 0 and out.max() == 200


def test_maps_scale_for_other_source_size():
    model = solve_warp(pattern.grid_points(), pattern.grid_points())   # identity-like
    maps = reference.build_maps(model, source_size=(720, 1280))
    assert maps.map_x.max() <= 720 + 1 and maps.map_y.max() <= 1280 + 1


def test_prepare_source_rotation_and_scale():
    landscape = np.zeros((1080, 1920, 3), np.uint8)
    landscape[:, :960] = 255                          # left half white
    out = reference.prepare_source(landscape, PANEL, rotation=90)
    assert out.shape == (PANEL[1], PANEL[0], 3)
    assert out[:PANEL[1] // 2].mean() > 200             # left half rotated to the top
    assert out[PANEL[1] // 2:].mean() < 50
    flipped = reference.prepare_source(landscape, PANEL, rotation=90, flip_vertical=True)
    assert flipped[:PANEL[1] // 2].mean() < 50


def test_test_card_shape():
    card = reference.test_card(PANEL)
    assert card.shape == (PANEL[1], PANEL[0], 3)
