"""One-time camera lens calibration (task 1.3).

Reads 15 to 20 photos of a flat printed target, finds the target in each,
runs OpenCV's calibration, and writes the camera matrix and distortion
coefficients to a JSON file that warpei.calibration.undistort loads.

Print the target with:
    python -m warpei.calibration.pattern --out target.png
and mount it flat on a rigid board. Photograph it with the camera at its
working focus, tilting the board and covering the corners of the frame.
Lock the focus ring afterwards; changing focus changes the result.

Run from the sbc/ folder:
    python tools/calibrate_camera.py photos/*.png --out camera.json
    python tools/calibrate_camera.py photos/*.png --chessboard 9 6
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

SBC_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SBC_ROOT))

from warpei.calibration.detect import detect_grid                 # noqa: E402
from warpei.calibration.pattern import PATTERN_SIZE               # noqa: E402
from warpei.calibration.undistort import CameraCalibration        # noqa: E402

MIN_VIEWS = 10
TARGET_RMS = 0.5           # pixels; the task 1.3 acceptance limit
OUTLIER_FACTOR = 2.0       # views worse than this multiple of the median are dropped


def circle_grid_object_points(pattern_size: tuple[int, int] = PATTERN_SIZE) -> np.ndarray:
    """Target geometry for the asymmetric grid, in grid units, same order as detect.py.

    Absolute scale does not matter for intrinsics, so the unit is left as 1.
    """
    cols, rows = pattern_size
    pts = [(2 * c + r % 2, r, 0) for r in range(rows) for c in range(cols)]
    return np.array(pts, dtype=np.float32)


def chessboard_object_points(inner: tuple[int, int]) -> np.ndarray:
    cols, rows = inner
    pts = [(c, r, 0) for r in range(rows) for c in range(cols)]
    return np.array(pts, dtype=np.float32)


def find_target(image: np.ndarray, chessboard: tuple[int, int] | None) -> np.ndarray | None:
    """Return the target's image points, or None if it was not found."""
    if chessboard is None:
        result = detect_grid(image)
        return result.centers if result.found else None

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    found, corners = cv2.findChessboardCorners(
        gray, chessboard, flags=cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
    if not found:
        return None
    corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1),
                               (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001))
    return corners.reshape(-1, 2)


def per_view_errors(obj_pts, img_pts, matrix, dist, rvecs, tvecs) -> list[float]:
    errors = []
    for o, i, r, t in zip(obj_pts, img_pts, rvecs, tvecs):
        projected, _ = cv2.projectPoints(o, r, t, matrix, dist)
        errors.append(float(np.sqrt(np.mean(np.sum((projected.reshape(-1, 2) - i) ** 2, axis=1)))))
    return errors


def calibrate(obj_pts, img_pts, image_size):
    flags = 0  # standard 5-coefficient model: k1, k2, p1, p2, k3
    rms, matrix, dist, rvecs, tvecs = cv2.calibrateCamera(
        obj_pts, img_pts, image_size, None, None, flags=flags)
    return rms, matrix, dist, per_view_errors(obj_pts, img_pts, matrix, dist, rvecs, tvecs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("images", nargs="+", help="photos of the flat target")
    parser.add_argument("--out", default="camera.json")
    parser.add_argument("--chessboard", type=int, nargs=2, metavar=("COLS", "ROWS"),
                        help="use a chessboard with this many inner corners instead of the circle grid")
    parser.add_argument("--keep-outliers", action="store_true",
                        help="do not drop views with unusually high error")
    args = parser.parse_args()
    chessboard = tuple(args.chessboard) if args.chessboard else None

    obj_template = (chessboard_object_points(chessboard) if chessboard
                    else circle_grid_object_points())
    obj_pts, img_pts, names = [], [], []
    image_size = None

    for path in args.images:
        image = cv2.imread(path)
        if image is None:
            print(f"{path}: could not read, skipped")
            continue
        size = (image.shape[1], image.shape[0])
        if image_size is None:
            image_size = size
        elif size != image_size:
            print(f"{path}: {size[0]}x{size[1]} differs from {image_size[0]}x{image_size[1]}, skipped")
            continue
        points = find_target(image, chessboard)
        if points is None:
            print(f"{path}: target not found, skipped")
            continue
        obj_pts.append(obj_template.copy())
        img_pts.append(points.astype(np.float32))
        names.append(Path(path).name)
        print(f"{path}: ok")

    if len(img_pts) < MIN_VIEWS:
        raise SystemExit(f"Only {len(img_pts)} usable views; need at least {MIN_VIEWS}.")

    rms, matrix, dist, errors = calibrate(obj_pts, img_pts, image_size)
    print(f"\nFirst pass: {len(img_pts)} views, RMS {rms:.3f} px")

    if not args.keep_outliers:
        limit = OUTLIER_FACTOR * float(np.median(errors))
        keep = [i for i, e in enumerate(errors) if e <= limit]
        dropped = [names[i] for i, e in enumerate(errors) if e > limit]
        if dropped and len(keep) >= MIN_VIEWS:
            print(f"Dropping {len(dropped)} outlier view(s): {', '.join(dropped)}")
            obj_pts = [obj_pts[i] for i in keep]
            img_pts = [img_pts[i] for i in keep]
            names = [names[i] for i in keep]
            rms, matrix, dist, errors = calibrate(obj_pts, img_pts, image_size)
            print(f"Second pass: {len(img_pts)} views, RMS {rms:.3f} px")

    calib = CameraCalibration(matrix, dist, image_size, rms, errors, names)
    calib.save(args.out)

    fx, fy = matrix[0, 0], matrix[1, 1]
    print(f"\nFocal length  fx {fx:.1f}  fy {fy:.1f} px")
    print(f"Principal pt  ({matrix[0, 2]:.1f}, {matrix[1, 2]:.1f}) px  "
          f"(image centre {image_size[0] / 2:.0f}, {image_size[1] / 2:.0f})")
    print(f"Distortion    {np.round(dist.reshape(-1), 5).tolist()}")
    print(f"Per-view RMS  min {min(errors):.3f}  max {max(errors):.3f} px")
    print(f"Wrote {args.out}")
    if rms > TARGET_RMS:
        print(f"WARNING: RMS {rms:.3f} px is above the {TARGET_RMS} px target. "
              "Check focus, add views near the frame corners, or try the rational model.")


if __name__ == "__main__":
    main()
