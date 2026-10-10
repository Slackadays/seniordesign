"""Find the calibration circle centres in a camera image.

The centres come back in the same order as pattern.grid_points(), so
centres[i] is the camera-side match of projected point i.

Run as a script to check a saved capture:
    python -m warpei.calibration.detect capture.jpg --show
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import cv2
import numpy as np

from .pattern import PATTERN_SIZE


@dataclass
class DetectionResult:
    found: bool
    centers: np.ndarray        # shape (N, 2), float32, camera pixels; empty if not found
    attempt: str               # which strategy succeeded, for logging and the report
    blob_count: int            # blobs seen by the detector, useful when tuning


def make_blob_detector(image_shape: tuple[int, ...]) -> cv2.SimpleBlobDetector:
    """Build a blob detector with area limits scaled to the image size.

    Limits are deliberately wide: the circles change size with throw distance
    and appear as ellipses on a curved surface.
    """
    height, width = image_shape[:2]
    image_area = float(height * width)

    params = cv2.SimpleBlobDetector_Params()
    params.filterByColor = True
    params.blobColor = 0                     # dark blobs; light patterns are inverted first

    params.filterByArea = True
    params.minArea = max(20.0, image_area * 1e-5)    # about 20 px^2 at 1080p
    params.maxArea = image_area * 5e-3               # about 10,000 px^2 at 1080p

    params.filterByCircularity = True
    params.minCircularity = 0.6              # tolerate ellipses

    params.filterByConvexity = True
    params.minConvexity = 0.8

    params.filterByInertia = True
    params.minInertiaRatio = 0.2             # tolerate strong foreshortening

    params.minThreshold = 10
    params.maxThreshold = 220
    params.thresholdStep = 10
    params.minDistBetweenBlobs = 4
    return cv2.SimpleBlobDetector_create(params)


def _to_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image


def _preprocess(gray: np.ndarray, equalize: bool) -> np.ndarray:
    """Light blur to suppress sensor noise; optional local contrast boost."""
    out = cv2.GaussianBlur(gray, (5, 5), 0)
    if equalize:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        out = clahe.apply(out)
    return out


def detect_grid(image: np.ndarray,
                pattern_size: tuple[int, int] = PATTERN_SIZE,
                dark_on_light: bool = True) -> DetectionResult:
    """Locate the asymmetric circle grid.

    Tries a short list of strategies in order and returns on the first hit:
    plain detection, then the clustering variant (more tolerant of perspective),
    then both again after a local contrast boost.

    dark_on_light must match how the pattern was rendered in pattern.py.
    """
    gray = _to_gray(image)
    if not dark_on_light:
        gray = cv2.bitwise_not(gray)

    detector = make_blob_detector(gray.shape)
    expected = pattern_size[0] * pattern_size[1]

    base = cv2.CALIB_CB_ASYMMETRIC_GRID
    attempts = [
        ("plain", False, base),
        ("clustering", False, base | cv2.CALIB_CB_CLUSTERING),
        ("equalized", True, base),
        ("equalized+clustering", True, base | cv2.CALIB_CB_CLUSTERING),
    ]

    blob_count = 0
    for name, equalize, flags in attempts:
        prepared = _preprocess(gray, equalize)
        blob_count = len(detector.detect(prepared))
        found, centers = cv2.findCirclesGrid(prepared, pattern_size,
                                             flags=flags, blobDetector=detector)
        if found and centers is not None and len(centers) == expected:
            return DetectionResult(True, centers.reshape(-1, 2).astype(np.float32),
                                   name, blob_count)

    return DetectionResult(False, np.empty((0, 2), dtype=np.float32), "none", blob_count)


def draw_detection(image: np.ndarray, result: DetectionResult,
                   pattern_size: tuple[int, int] = PATTERN_SIZE) -> np.ndarray:
    """Return a colour copy of the image with the detected grid drawn on it."""
    canvas = image.copy() if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if result.found:
        cv2.drawChessboardCorners(canvas, pattern_size,
                                  result.centers.reshape(-1, 1, 2), True)
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect the circle grid in saved images.")
    parser.add_argument("images", nargs="+")
    parser.add_argument("--light-on-dark", action="store_true")
    parser.add_argument("--show", action="store_true", help="display the result window")
    parser.add_argument("--save", action="store_true", help="write <name>_detected.png")
    args = parser.parse_args()

    hits = 0
    for path in args.images:
        image = cv2.imread(path)
        if image is None:
            print(f"{path}: could not read file")
            continue
        result = detect_grid(image, dark_on_light=not args.light_on_dark)
        hits += result.found
        status = f"found ({result.attempt})" if result.found else "NOT found"
        print(f"{path}: {status}, {result.blob_count} blobs")
        if args.show or args.save:
            canvas = draw_detection(image, result)
            if args.save:
                cv2.imwrite(path.rsplit(".", 1)[0] + "_detected.png", canvas)
            if args.show:
                cv2.imshow(path, canvas)
                cv2.waitKey(0)
    print(f"Detected {hits} of {len(args.images)}")


if __name__ == "__main__":
    main()