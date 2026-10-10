"""Generate the projected calibration target: a 4 x 11 asymmetric circle grid.

The point order matches OpenCV's findCirclesGrid for CALIB_CB_ASYMMETRIC_GRID,
so grid_points()[i] corresponds to the i-th centre returned by detect.py.

Run as a script to write the pattern image:
    python -m warpei.calibration.pattern --out pattern.png
"""

from __future__ import annotations

import argparse

import cv2
import numpy as np

# Panel resolution in its native (portrait) orientation.
PANEL_WIDTH = 1440
PANEL_HEIGHT = 2560

# OpenCV convention: (circles per row, number of rows).
PATTERN_SIZE = (4, 11)

# Fraction of each panel dimension the grid may occupy. Keeps circles away
# from the edges, where the curved surface distorts and defocuses the most.
FILL_FRACTION = 0.80

# Circle radius as a fraction of the grid unit. Nearest neighbours sit
# 1.41 units apart, so 0.30 leaves a clear gap between circles.
RADIUS_FRACTION = 0.30


def grid_unit(width: int = PANEL_WIDTH, height: int = PANEL_HEIGHT,
              pattern_size: tuple[int, int] = PATTERN_SIZE,
              fill: float = FILL_FRACTION) -> float:
    """Return the grid unit in panel pixels.

    In an asymmetric grid, circles in a row are 2 units apart, odd rows are
    shifted by 1 unit, and rows are 1 unit apart.
    """
    cols, rows = pattern_size
    span_x = 2 * (cols - 1) + 1   # units across, including the stagger
    span_y = rows - 1             # units down
    return min(fill * width / span_x, fill * height / span_y)


def grid_points(width: int = PANEL_WIDTH, height: int = PANEL_HEIGHT,
                pattern_size: tuple[int, int] = PATTERN_SIZE,
                fill: float = FILL_FRACTION) -> np.ndarray:
    """Return the circle centres in panel pixels, shape (N, 2), float32.

    Order: row by row, left to right, same as findCirclesGrid.
    """
    cols, rows = pattern_size
    unit = grid_unit(width, height, pattern_size, fill)
    span_x = (2 * (cols - 1) + 1) * unit
    span_y = (rows - 1) * unit
    x0 = (width - span_x) / 2.0
    y0 = (height - span_y) / 2.0

    points = []
    for row in range(rows):
        for col in range(cols):
            x = x0 + (2 * col + row % 2) * unit
            y = y0 + row * unit
            points.append((x, y))
    return np.array(points, dtype=np.float32)


def circle_radius(width: int = PANEL_WIDTH, height: int = PANEL_HEIGHT,
                  pattern_size: tuple[int, int] = PATTERN_SIZE,
                  fill: float = FILL_FRACTION) -> int:
    """Return the circle radius in panel pixels."""
    return int(round(RADIUS_FRACTION * grid_unit(width, height, pattern_size, fill)))


def render_pattern(width: int = PANEL_WIDTH, height: int = PANEL_HEIGHT,
                   pattern_size: tuple[int, int] = PATTERN_SIZE,
                   fill: float = FILL_FRACTION,
                   dark_on_light: bool = True) -> np.ndarray:
    """Draw the pattern as an 8-bit grayscale image of shape (height, width).

    dark_on_light=True draws black circles on a white field, which is what
    OpenCV's default blob detector looks for.
    """
    background, foreground = (255, 0) if dark_on_light else (0, 255)
    image = np.full((height, width), background, dtype=np.uint8)
    radius = circle_radius(width, height, pattern_size, fill)
    for x, y in grid_points(width, height, pattern_size, fill):
        cv2.circle(image, (int(round(x)), int(round(y))), radius,
                   foreground, thickness=-1, lineType=cv2.LINE_AA)
    return image


def main() -> None:
    parser = argparse.ArgumentParser(description="Write the calibration pattern image.")
    parser.add_argument("--out", default="pattern.png")
    parser.add_argument("--width", type=int, default=PANEL_WIDTH)
    parser.add_argument("--height", type=int, default=PANEL_HEIGHT)
    parser.add_argument("--light-on-dark", action="store_true",
                        help="white circles on black instead of black on white")
    args = parser.parse_args()

    image = render_pattern(args.width, args.height,
                           dark_on_light=not args.light_on_dark)
    cv2.imwrite(args.out, image)
    print(f"Wrote {args.out}: {args.width}x{args.height}, "
          f"{len(grid_points(args.width, args.height))} circles, "
          f"radius {circle_radius(args.width, args.height)} px")


if __name__ == "__main__":
    main()