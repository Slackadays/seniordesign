"""Task 1.2: circle-grid detection.

Acceptance: grid found in at least 90% of the real image set, and the
returned order matches pattern.grid_points(). The simulated cases run
everywhere; the real-image case runs once tests/data/ has photos.
"""

from __future__ import annotations

import numpy as np
import pytest

from conftest import sim_camera
from warpei.calibration import pattern
from warpei.calibration.detect import detect_grid

REQUIRED_RATE = 0.90


def test_clean_pattern_is_detected_in_order():
    image = pattern.render_pattern()
    result = detect_grid(image)
    assert result.found
    assert result.centers.shape == (44, 2)
    assert np.abs(result.centers - pattern.grid_points()).max() < 1.0


def test_order_matches_grid_points_under_perspective():
    view = sim_camera(bow=0.0, blur=1.0, distort=False)
    result = detect_grid(view.image)
    assert result.found
    # Same order as the panel points: each detected centre near its ideal spot.
    assert np.abs(result.centers - view.ideal_camera_points).max() < 1.0


@pytest.mark.parametrize("scale,bow,blur,seed", [
    (0.17, 1.0, 2.0, 1), (0.22, 1.0, 3.0, 2), (0.30, 1.5, 4.0, 3), (0.15, 0.5, 1.5, 4),
])
def test_detects_through_simulated_optics(scale, bow, blur, seed):
    view = sim_camera(scale=scale, bow=bow, blur=blur, seed=seed)
    result = detect_grid(view.image)
    assert result.found, f"not found: {result.blob_count} blobs seen"


def test_light_on_dark_pattern():
    view = sim_camera(panel_image=pattern.render_pattern(dark_on_light=False), blur=1.0)
    assert detect_grid(view.image, dark_on_light=False).found


def test_shifted_verify_pattern_is_detected():
    view = sim_camera(offset=pattern.VERIFY_OFFSET, blur=1.5)
    result = detect_grid(view.image)
    assert result.found
    undistorted = view.camera.undistort_points(result.centers)
    assert np.abs(undistorted - view.ideal_camera_points).max() < 1.0


def test_blank_image_is_not_found():
    blank = np.full((1080, 1920, 3), 90, np.uint8)
    result = detect_grid(blank)
    assert not result.found
    assert result.centers.shape == (0, 2)


def test_real_image_set(real_images):
    if len(real_images) < 10:
        pytest.skip("fewer than 10 photos in tests/data/; run tools/capture_frames.py first")
    import cv2
    found = sum(detect_grid(cv2.imread(str(p))).found for p in real_images)
    rate = found / len(real_images)
    print(f"\nreal images: {found}/{len(real_images)} detected ({rate:.0%})")
    assert rate >= REQUIRED_RATE, f"detection rate {rate:.0%} is below {REQUIRED_RATE:.0%}"
