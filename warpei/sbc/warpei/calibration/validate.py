"""Score a calibration (task 1.5).

The specification in Table 2.5.1 is the RMS distance between where the
circles appear and where they should appear, over the n detected circles:

    RMS = sqrt( (1/n) * sum_i |c_i - T(p_i)|^2 )

c_i   detected centre after lens undistortion, camera pixels
T(p)  where panel point p should land in the camera after correction

Scoring the same 44 points that were used to fit the model understates the
error, so the verify step projects a grid shifted by half a pitch
(pattern.VERIFY_OFFSET) through the correction and scores that instead.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .solve import WarpModel


@dataclass
class ErrorReport:
    rms: float              # camera pixels
    mean: float
    max: float
    count: int
    residuals: np.ndarray   # (N, 2) detected - expected

    def to_dict(self) -> dict:
        return {"rms": self.rms, "mean": self.mean, "max": self.max, "count": self.count}


def rms_error(detected: np.ndarray, expected: np.ndarray) -> ErrorReport:
    """RMS, mean and max distance between matched point sets."""
    d = np.asarray(detected, dtype=np.float64).reshape(-1, 2)
    e = np.asarray(expected, dtype=np.float64).reshape(-1, 2)
    if d.shape != e.shape:
        raise ValueError(f"{len(d)} detected points but {len(e)} expected points")
    if len(d) == 0:
        raise ValueError("no points to score")
    residuals = d - e
    dist = np.sqrt(np.sum(residuals ** 2, axis=1))
    return ErrorReport(float(np.sqrt(np.mean(dist ** 2))), float(dist.mean()),
                       float(dist.max()), len(d), residuals)


def expected_positions(model: WarpModel, panel_points: np.ndarray) -> np.ndarray:
    """Where panel points should appear in the camera once the correction is applied."""
    return model.target(panel_points)


def uncorrected_error(model: WarpModel, panel_points: np.ndarray,
                      detected: np.ndarray) -> ErrorReport:
    """Error of the raw projection: detected centres against the target grid.

    This is the "before" number. It uses the same target T as the "after"
    number, so the two are directly comparable.
    """
    return rms_error(detected, expected_positions(model, panel_points))


def corrected_error(model: WarpModel, panel_points: np.ndarray,
                    detected: np.ndarray) -> ErrorReport:
    """Error after correction: detected centres of the pre-warped pattern
    against the target grid. The "after" number."""
    return rms_error(detected, expected_positions(model, panel_points))


def predicted_corrected_positions(model: WarpModel, panel_points: np.ndarray) -> np.ndarray:
    """Where the model itself predicts corrected circles will appear.

    The corrected image shows source pixel T^-1(f(q)) at panel pixel q, so a
    circle drawn at source point p appears at the panel pixel q with
    f(q) = T(p). By construction the camera then sees it at T(p); this
    function exists so tests and simulations can check that chain.
    """
    return model.target(panel_points)


def percent_reduction(before: ErrorReport, after: ErrorReport) -> float:
    """Percent by which the RMS fell. 50 or more meets the specification."""
    if before.rms == 0:
        return 0.0
    return 100.0 * (1.0 - after.rms / before.rms)


def meets_specification(before: ErrorReport, after: ErrorReport,
                        required_reduction: float = 50.0) -> bool:
    return percent_reduction(before, after) >= required_reduction


def summary(before: ErrorReport, after: ErrorReport) -> str:
    return (f"RMS before {before.rms:.2f} px, after {after.rms:.2f} px, "
            f"reduction {percent_reduction(before, after):.1f}% "
            f"({'PASS' if meets_specification(before, after) else 'FAIL'} at 50%)")
