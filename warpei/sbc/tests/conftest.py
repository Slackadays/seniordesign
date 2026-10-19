"""Shared test fixtures: a simulated camera so the tests run with no hardware.

sim_camera() renders the calibration pattern as a 1920 x 1080 camera would
see it: small in the frame, tilted (a homography), bowed like a cylinder,
blurred, noisy, on a grey background, with a known lens distortion applied
last. Because every step is known, the tests can compare detected and
solved results against ground truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pytest

from warpei.calibration import pattern
from warpei.calibration.undistort import CameraCalibration

DATA_DIR = Path(__file__).parent / "data"
CAM_W, CAM_H = 1920, 1080


def make_camera_calibration(k1: float = -0.12, k2: float = 0.03,
                            p1: float = 0.001, p2: float = -0.0005) -> CameraCalibration:
    """A plausible wide-angle lens model for simulation."""
    matrix = np.array([[1000.0, 0, CAM_W / 2], [0, 1000.0, CAM_H / 2], [0, 0, 1]])
    return CameraCalibration(matrix, np.array([[k1, k2, p1, p2, 0.0]]), (CAM_W, CAM_H))


@dataclass
class SimulatedView:
    image: np.ndarray                 # BGR camera frame
    panel_points: np.ndarray          # (44, 2) panel pixels of the drawn circles
    ideal_camera_points: np.ndarray   # (44, 2) where the centres are before lens distortion
    camera: CameraCalibration
    homography: np.ndarray
    bow: float


def surface_map(points: np.ndarray, H: np.ndarray, bow: float) -> np.ndarray:
    """Panel points -> ideal camera points: a homography then a smooth bow."""
    cam = cv2.perspectiveTransform(np.asarray(points, np.float64).reshape(-1, 1, 2), H).reshape(-1, 2)
    x, y = cam[:, 0], cam[:, 1]
    xb = x + bow * ((y - CAM_H / 2) / (CAM_H / 2)) ** 2 * 40.0
    yb = y + bow * ((x - CAM_W / 2) / 300.0) ** 2 * 8.0
    return np.stack([xb, yb], axis=1)


def sim_camera(scale: float = 0.17, bow: float = 1.0, blur: float = 2.0,
               distort: bool = True, noise: float = 4.0, seed: int = 0,
               offset: tuple[float, float] = (0.0, 0.0),
               panel_image: np.ndarray | None = None) -> SimulatedView:
    """Render the pattern (or a given panel image) through a simulated optical path."""
    panel = pattern.render_pattern(offset=offset) if panel_image is None else panel_image
    H = np.array([[scale, 0.03, 820.0], [0.02, scale, 60.0], [2e-5, 1e-5, 1.0]])
    cam = make_camera_calibration() if distort else CameraCalibration(
        make_camera_calibration().camera_matrix, np.zeros((1, 5)), (CAM_W, CAM_H))

    # Build the full inverse map (camera pixel -> panel pixel) and remap once.
    yy, xx = np.mgrid[0:CAM_H, 0:CAM_W].astype(np.float64)
    grid = np.stack([xx.ravel(), yy.ravel()], axis=1)
    undist = cam.undistort_points(grid).astype(np.float64)        # ideal camera coords
    # Invert the bow approximately (it is small): subtract the bow at the ideal point.
    x, y = undist[:, 0], undist[:, 1]
    xu = x - bow * ((y - CAM_H / 2) / (CAM_H / 2)) ** 2 * 40.0
    yu = y - bow * ((x - CAM_W / 2) / 300.0) ** 2 * 8.0
    flat = cv2.perspectiveTransform(np.stack([xu, yu], axis=1).reshape(-1, 1, 2),
                                    np.linalg.inv(H)).reshape(-1, 2)
    map_x = flat[:, 0].reshape(CAM_H, CAM_W).astype(np.float32)
    map_y = flat[:, 1].reshape(CAM_H, CAM_W).astype(np.float32)
    image = cv2.remap(panel, map_x, map_y, cv2.INTER_LINEAR,
                      borderMode=cv2.BORDER_CONSTANT, borderValue=60)
    if blur > 0:
        image = cv2.GaussianBlur(image, (0, 0), blur)
    rng = np.random.default_rng(seed)
    image = (image * 0.7 + 30 + rng.normal(0, noise, image.shape)).clip(0, 255).astype(np.uint8)
    image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

    panel_pts = pattern.grid_points(offset=offset)
    ideal = surface_map(panel_pts, H, bow)
    return SimulatedView(image, panel_pts, ideal.astype(np.float32), cam, H, bow)


@pytest.fixture
def simulated_view() -> SimulatedView:
    return sim_camera()


@pytest.fixture
def real_images() -> list[Path]:
    """Photos in tests/data/, if task 1.1 has produced any."""
    if not DATA_DIR.exists():
        return []
    return sorted(p for p in DATA_DIR.iterdir()
                  if p.suffix.lower() in {".png", ".jpg", ".jpeg"})
