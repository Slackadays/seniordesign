"""Fit the warp model from matched panel and camera points (task 1.4).

Inputs are the 44 panel-pixel centres from pattern.grid_points() and the
44 camera-pixel centres from detect.py, already undistorted. The model has
two parts that together form the forward map f: panel pixel -> camera pixel.

    f(p) = H(n(p)) + poly(n(p))

n   scales panel pixels to the range -1..1 (keeps the fit well conditioned)
H   homography: removes the perspective component (flat-surface case)
poly second-order bivariate polynomial on the residual, 6 coefficients per
    axis, 12 in total: what the curved surface adds

The target map T places the source image as an undistorted rectangle in the
camera's view: T(p) = s * p + t. The corrected image shows, at panel pixel p,
the source pixel T^-1(f(p)). No numerical inversion of the polynomial is
needed; T is a scale and offset, so T^-1 is trivial.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .pattern import PANEL_HEIGHT, PANEL_WIDTH

MIN_POINTS = 6           # a 6-coefficient fit needs at least 6 points per axis
SHRINK_STEP = 0.01       # scale step when fitting the target rectangle inside the footprint


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------

def design_matrix(xn: np.ndarray, yn: np.ndarray) -> np.ndarray:
    """One row per point: [1, x, y, x^2, xy, y^2]."""
    return np.stack([np.ones_like(xn), xn, yn, xn * xn, xn * yn, yn * yn], axis=1)


@dataclass
class WarpModel:
    panel_size: tuple[int, int]                 # (width, height)
    homography: np.ndarray                      # 3 x 3, normalised panel -> camera pixels
    coeff_u: np.ndarray                         # 6, residual polynomial, camera x
    coeff_v: np.ndarray                         # 6, residual polynomial, camera y
    target_scale: float                         # T: camera = scale * panel + offset
    target_offset: np.ndarray                   # 2
    fit_rms: float = 0.0                        # camera px, on the points used for the fit
    homography_rms: float = 0.0                 # camera px, homography alone
    shrink: float = 0.0                         # fraction of area given up to fit the rectangle
    extra: dict = field(default_factory=dict)   # free-form notes (timestamps, attempt, ...)

    # ---- coordinate helpers ---------------------------------------------

    def normalize(self, panel_points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        w, h = self.panel_size
        p = np.asarray(panel_points, dtype=np.float64).reshape(-1, 2)
        return (p[:, 0] - w / 2.0) / (w / 2.0), (p[:, 1] - h / 2.0) / (h / 2.0)

    def forward(self, panel_points: np.ndarray) -> np.ndarray:
        """f: panel pixels -> camera pixels, shape (N, 2)."""
        xn, yn = self.normalize(panel_points)
        hom = cv2.perspectiveTransform(
            np.stack([xn, yn], axis=1).reshape(-1, 1, 2), self.homography).reshape(-1, 2)
        a = design_matrix(xn, yn)
        return (hom + np.stack([a @ self.coeff_u, a @ self.coeff_v], axis=1)).astype(np.float32)

    def target(self, panel_points: np.ndarray) -> np.ndarray:
        """T: where a panel pixel should appear in the camera after correction."""
        p = np.asarray(panel_points, dtype=np.float64).reshape(-1, 2)
        return (self.target_scale * p + self.target_offset).astype(np.float32)

    def target_inverse(self, camera_points: np.ndarray) -> np.ndarray:
        c = np.asarray(camera_points, dtype=np.float64).reshape(-1, 2)
        return ((c - self.target_offset) / self.target_scale).astype(np.float32)

    def source_lookup(self, panel_points: np.ndarray) -> np.ndarray:
        """Which source pixel each panel pixel must display: T^-1(f(p))."""
        return self.target_inverse(self.forward(panel_points))

    # ---- serialisation ---------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "panel_size": list(self.panel_size),
            "homography": self.homography.tolist(),
            "coeff_u": self.coeff_u.tolist(),
            "coeff_v": self.coeff_v.tolist(),
            "target_scale": float(self.target_scale),
            "target_offset": self.target_offset.tolist(),
            "fit_rms": float(self.fit_rms),
            "homography_rms": float(self.homography_rms),
            "shrink": float(self.shrink),
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WarpModel":
        return cls(
            panel_size=(int(d["panel_size"][0]), int(d["panel_size"][1])),
            homography=np.array(d["homography"], dtype=np.float64).reshape(3, 3),
            coeff_u=np.array(d["coeff_u"], dtype=np.float64).reshape(6),
            coeff_v=np.array(d["coeff_v"], dtype=np.float64).reshape(6),
            target_scale=float(d["target_scale"]),
            target_offset=np.array(d["target_offset"], dtype=np.float64).reshape(2),
            fit_rms=float(d.get("fit_rms", 0.0)),
            homography_rms=float(d.get("homography_rms", 0.0)),
            shrink=float(d.get("shrink", 0.0)),
            extra=dict(d.get("extra", {})),
        )


# --------------------------------------------------------------------------
# Fitting
# --------------------------------------------------------------------------

def _rms(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.sum((np.asarray(a, float) - np.asarray(b, float)) ** 2, axis=1))))


def fit_similarity(panel_points: np.ndarray, camera_points: np.ndarray) -> tuple[float, np.ndarray]:
    """Least-squares scale and offset (no rotation) mapping panel -> camera.

    Rotation is excluded on purpose: the pre-rotation of the image is fixed by
    config, and a residual rotation here would appear as tilt in the output.
    """
    p = np.asarray(panel_points, float).reshape(-1, 2)
    c = np.asarray(camera_points, float).reshape(-1, 2)
    pm, cm = p.mean(axis=0), c.mean(axis=0)
    pc, cc = p - pm, c - cm
    scale = float(np.sum(pc * cc) / np.sum(pc * pc))
    return scale, cm - scale * pm


def footprint_polygon(model: WarpModel, samples_per_edge: int = 40) -> np.ndarray:
    """The panel border mapped into the camera: the region the projector can light."""
    w, h = model.panel_size
    t = np.linspace(0, 1, samples_per_edge, endpoint=False)
    border = np.concatenate([
        np.stack([t * w, np.zeros_like(t)], axis=1),
        np.stack([np.full_like(t, w), t * h], axis=1),
        np.stack([(1 - t) * w, np.full_like(t, h)], axis=1),
        np.stack([np.zeros_like(t), (1 - t) * h], axis=1),
    ])
    return model.forward(border).astype(np.float32)


def fit_target(model: WarpModel, panel_points: np.ndarray, camera_points: np.ndarray) -> None:
    """Choose T so the corrected rectangle lies inside the lit footprint.

    Starts from the best-fit scale and offset of the ideal grid in the camera
    image, then shrinks the scale about the grid centre, 1% at a time, until
    all four panel corners map inside the footprint. Sets target_scale,
    target_offset and shrink on the model in place.
    """
    scale0, offset0 = fit_similarity(panel_points, camera_points)
    w, h = model.panel_size
    corners = np.array([[0, 0], [w, 0], [w, h], [0, h]], float)
    centre = np.array([w / 2.0, h / 2.0])
    centre_cam = scale0 * centre + offset0
    poly = footprint_polygon(model).reshape(-1, 1, 2)

    scale = scale0
    while scale > 0.1 * scale0:
        cam_corners = centre_cam + scale * (corners - centre)
        inside = all(cv2.pointPolygonTest(poly, (float(x), float(y)), False) >= 0
                     for x, y in cam_corners)
        if inside:
            break
        scale -= SHRINK_STEP * scale0
    model.target_scale = scale
    model.target_offset = centre_cam - scale * centre
    model.shrink = 1.0 - (scale / scale0) ** 2


def solve_warp(panel_points: np.ndarray, camera_points: np.ndarray,
               panel_size: tuple[int, int] = (PANEL_WIDTH, PANEL_HEIGHT)) -> WarpModel:
    """Fit the full warp model from matched points.

    Raises ValueError if the point sets do not match or are too few.
    """
    p = np.asarray(panel_points, dtype=np.float64).reshape(-1, 2)
    c = np.asarray(camera_points, dtype=np.float64).reshape(-1, 2)
    if p.shape != c.shape:
        raise ValueError(f"{len(p)} panel points but {len(c)} camera points")
    if len(p) < MIN_POINTS:
        raise ValueError(f"need at least {MIN_POINTS} points, got {len(p)}")
    if not np.all(np.isfinite(c)):
        raise ValueError("camera points contain NaN or inf")

    model = WarpModel(panel_size, np.eye(3), np.zeros(6), np.zeros(6), 1.0, np.zeros(2))
    xn, yn = model.normalize(p)
    pn = np.stack([xn, yn], axis=1)

    # 1. Homography by plain least squares (method 0): no RANSAC, every point counts.
    H, _ = cv2.findHomography(pn.reshape(-1, 1, 2), c.reshape(-1, 1, 2), 0)
    if H is None:
        raise ValueError("homography fit failed; points may be degenerate")
    model.homography = H
    hom = cv2.perspectiveTransform(pn.reshape(-1, 1, 2), H).reshape(-1, 2)
    model.homography_rms = _rms(hom, c)

    # 2. Second-order polynomial on what the homography leaves behind.
    A = design_matrix(xn, yn)
    residual = c - hom
    model.coeff_u, *_ = np.linalg.lstsq(A, residual[:, 0], rcond=None)
    model.coeff_v, *_ = np.linalg.lstsq(A, residual[:, 1], rcond=None)
    model.fit_rms = _rms(model.forward(p), c)

    # 3. Target rectangle inside the footprint.
    fit_target(model, p, c)
    return model
