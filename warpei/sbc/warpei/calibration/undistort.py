"""Remove camera lens distortion from detected circle centres.

The camera is the measuring instrument. Any bend its lens adds to the circle
positions would be mistaken for surface curvature and "corrected"
into the projected image. This file loads the one-time lens calibration
written by tools/calibrate_camera.py and straightens the 44 detected points.

Only points are corrected, never whole images: 44 points per calibration
instead of 2 million pixels, and no resampling blur before detection.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np


@dataclass
class CameraCalibration:
    """Intrinsic camera parameters from cv2.calibrateCamera."""
    camera_matrix: np.ndarray            # 3 x 3
    dist_coeffs: np.ndarray              # 1 x 5 (k1, k2, p1, p2, k3)
    image_size: tuple[int, int]          # (width, height) the calibration was done at
    rms_reprojection_error: float = 0.0  # pixels, reported by calibrateCamera
    per_view_errors: list[float] = field(default_factory=list)
    source_images: list[str] = field(default_factory=list)

    # ---- serialisation ---------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "camera_matrix": self.camera_matrix.tolist(),
            "dist_coeffs": self.dist_coeffs.reshape(-1).tolist(),
            "image_size": list(self.image_size),
            "rms_reprojection_error": float(self.rms_reprojection_error),
            "per_view_errors": [float(e) for e in self.per_view_errors],
            "source_images": list(self.source_images),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CameraCalibration":
        return cls(
            camera_matrix=np.array(data["camera_matrix"], dtype=np.float64).reshape(3, 3),
            dist_coeffs=np.array(data["dist_coeffs"], dtype=np.float64).reshape(1, -1),
            image_size=(int(data["image_size"][0]), int(data["image_size"][1])),
            rms_reprojection_error=float(data.get("rms_reprojection_error", 0.0)),
            per_view_errors=list(data.get("per_view_errors", [])),
            source_images=list(data.get("source_images", [])),
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "CameraCalibration":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    # ---- use -------------------------------------------------------------

    def check_image_size(self, width: int, height: int) -> None:
        """Raise if a frame is not the size the calibration was made at.

        Intrinsics scale with resolution, so a mismatch gives wrong results.
        """
        if (width, height) != self.image_size:
            raise ValueError(
                f"frame is {width}x{height} but the camera was calibrated at "
                f"{self.image_size[0]}x{self.image_size[1]}; recalibrate or change the capture size")

    def undistort_points(self, points: np.ndarray) -> np.ndarray:
        """Map distorted pixel coordinates to ideal pixel coordinates.

        Passing the camera matrix as P keeps the result in pixel units, so the
        output can be used in place of the detected centres.
        """
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 1, 2)
        out = cv2.undistortPoints(pts, self.camera_matrix, self.dist_coeffs,
                                  P=self.camera_matrix)
        return out.reshape(-1, 2).astype(np.float32)

    def distort_points(self, points: np.ndarray) -> np.ndarray:
        """Inverse of undistort_points, used by tests and simulations.

        Applies the Brown radial and tangential model to ideal pixel points.
        """
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 2)
        fx, fy = self.camera_matrix[0, 0], self.camera_matrix[1, 1]
        cx, cy = self.camera_matrix[0, 2], self.camera_matrix[1, 2]
        k = np.zeros(5)
        k[:self.dist_coeffs.size] = self.dist_coeffs.reshape(-1)[:5]
        k1, k2, p1, p2, k3 = k

        x = (pts[:, 0] - cx) / fx
        y = (pts[:, 1] - cy) / fy
        r2 = x * x + y * y
        radial = 1 + k1 * r2 + k2 * r2 ** 2 + k3 * r2 ** 3
        xd = x * radial + 2 * p1 * x * y + p2 * (r2 + 2 * x * x)
        yd = y * radial + p1 * (r2 + 2 * y * y) + 2 * p2 * x * y
        return np.stack([xd * fx + cx, yd * fy + cy], axis=1).astype(np.float32)


def identity_calibration(width: int, height: int) -> CameraCalibration:
    """A no-distortion calibration, for running the pipeline before task 1.3 is done."""
    f = float(max(width, height))
    matrix = np.array([[f, 0, width / 2.0], [0, f, height / 2.0], [0, 0, 1]], dtype=np.float64)
    return CameraCalibration(matrix, np.zeros((1, 5)), (width, height))
