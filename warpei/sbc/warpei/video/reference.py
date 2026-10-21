"""CPU reference warp (task 2.1).

Turns a WarpModel into a per-pixel lookup map and applies it with OpenCV
remap. This is the renderer for the midterm demo, and afterwards the
known-good reference that the GPU shader output is compared against.

For each panel pixel q the map holds the source pixel T^-1(f(q)); pixels
whose lookup falls outside the source are painted black.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import cv2
import numpy as np

from ..calibration.solve import WarpModel


@dataclass
class WarpMaps:
    map_x: np.ndarray            # (H, W) float32, source x for each panel pixel
    map_y: np.ndarray            # (H, W) float32
    panel_size: tuple[int, int]  # (W, H)
    build_seconds: float


def build_maps(model: WarpModel, source_size: tuple[int, int] | None = None) -> WarpMaps:
    """Evaluate the model once for every panel pixel.

    source_size (w, h) is the size of the image that will be fed to
    warp_image. The model's lookup is in panel pixels; if the source is a
    different size it is scaled to fill the panel.
    """
    start = time.perf_counter()
    w, h = model.panel_size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    panel_pts = np.stack([xx.ravel(), yy.ravel()], axis=1)
    src = model.source_lookup(panel_pts)
    map_x = src[:, 0].reshape(h, w).astype(np.float32)
    map_y = src[:, 1].reshape(h, w).astype(np.float32)
    if source_size is not None and tuple(source_size) != (w, h):
        map_x *= source_size[0] / w
        map_y *= source_size[1] / h
    return WarpMaps(map_x, map_y, (w, h), time.perf_counter() - start)


def warp_image(source: np.ndarray, maps: WarpMaps,
               interpolation: int = cv2.INTER_LINEAR) -> np.ndarray:
    """Resample the source through the maps. Output is panel-sized."""
    return cv2.remap(source, maps.map_x, maps.map_y, interpolation,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def warp_model_image(source: np.ndarray, model: WarpModel) -> np.ndarray:
    """Convenience: build maps and warp in one call (slow; for one-off use)."""
    h, w = source.shape[:2]
    return warp_image(source, build_maps(model, (w, h)))


def prepare_source(image: np.ndarray, panel_size: tuple[int, int],
                   rotation: int = 0, flip_horizontal: bool = False,
                   flip_vertical: bool = False) -> np.ndarray:
    """Turn and scale a source frame to the panel's orientation and size.

    rotation is clockwise degrees (0, 90, 180, 270). A 1920 x 1080 laptop
    frame rotated 90 becomes 1080 x 1920 and scales by exactly 4/3 to the
    1440 x 2560 panel.
    """
    codes = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
             270: cv2.ROTATE_90_COUNTERCLOCKWISE}
    if rotation in codes:
        image = cv2.rotate(image, codes[rotation])
    elif rotation != 0:
        raise ValueError("rotation must be 0, 90, 180 or 270")
    if flip_horizontal and flip_vertical:
        image = cv2.flip(image, -1)
    elif flip_horizontal:
        image = cv2.flip(image, 1)
    elif flip_vertical:
        image = cv2.flip(image, 0)
    if (image.shape[1], image.shape[0]) != tuple(panel_size):
        image = cv2.resize(image, tuple(panel_size), interpolation=cv2.INTER_AREA)
    return image


def test_card(panel_size: tuple[int, int], spacing: int = 160) -> np.ndarray:
    """A straight-line grid with a border: shows curvature at a glance."""
    w, h = panel_size
    img = np.full((h, w, 3), 255, np.uint8)
    for x in range(0, w, spacing):
        cv2.line(img, (x, 0), (x, h - 1), (0, 0, 0), 3)
    for y in range(0, h, spacing):
        cv2.line(img, (0, y), (w - 1, y), (0, 0, 0), 3)
    cv2.rectangle(img, (0, 0), (w - 1, h - 1), (0, 0, 255), 12)
    cv2.circle(img, (w // 2, h // 2), min(w, h) // 4, (255, 0, 0), 8)
    return img
