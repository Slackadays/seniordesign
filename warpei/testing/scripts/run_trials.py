"""Run repeated calibrations and log each one (task 3.2).

    run_trials.py run --config CONFIG --count 20 --surface curved --distance-cm 90 --lighting dim
    run_trials.py summarize results.csv

`run --rig sim` drives the simulated camera from the test suite instead of
real hardware, to check the logging without a projector.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SBC = REPO / "sbc"
RESULTS_DIR = REPO / "testing" / "results"
sys.path.insert(0, str(SBC))

from warpei.app import Calibrator, CalibrationRun          # noqa: E402
from warpei.config import Config                            # noqa: E402

FIELDS = ["timestamp", "run", "surface", "distance_cm", "lighting", "passed",
          "rms_before", "rms_after", "reduction_percent", "seconds",
          "attempts_fit", "attempts_verify_raw", "attempts_verify_corrected",
          "homography_rms", "fit_rms", "shrink_percent", "error", "notes"]

PASS_WINDOW = 5
PASS_REQUIRED = 3
TIME_LIMIT = 180.0
DETECT_RATE_REQUIRED = 0.90


# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------

def row_from_run(run: CalibrationRun, index: int, args) -> dict:
    m = run.model
    return {
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "run": index,
        "surface": args.surface, "distance_cm": args.distance_cm, "lighting": args.lighting,
        "passed": "yes" if run.passed else "no",
        "rms_before": f"{run.rms_before:.3f}" if run.rms_before is not None else "",
        "rms_after": f"{run.rms_after:.3f}" if run.rms_after is not None else "",
        "reduction_percent": f"{run.reduction_percent:.1f}" if run.reduction_percent is not None else "",
        "seconds": f"{run.seconds:.2f}",
        "attempts_fit": run.attempts.get("fit grid", ""),
        "attempts_verify_raw": run.attempts.get("verify raw", ""),
        "attempts_verify_corrected": run.attempts.get("verify corrected", ""),
        "homography_rms": f"{m.homography_rms:.3f}" if m else "",
        "fit_rms": f"{m.fit_rms:.3f}" if m else "",
        "shrink_percent": f"{100 * m.shrink:.1f}" if m else "",
        "error": run.error, "notes": args.notes,
    }


def append_row(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if new:
            writer.writeheader()
        writer.writerow(row)


def make_rig(args, config: Config):
    """Return (display, capture, camera_calibration, release)."""
    if args.rig == "sim":
        sys.path.insert(0, str(SBC / "tests"))
        from test_app import FakeRig                       # the simulator used by the tests
        rig = FakeRig(bow=args.sim_bow, blur=args.sim_blur)
        return rig.display, rig.capture, rig.camera, lambda: None
    from warpei.app import OpenCVCamera, OpenCVDisplay, load_camera_calibration
    display = OpenCVDisplay(config)
    camera = OpenCVCamera(config)
    return display, camera, load_camera_calibration(config), camera.release


def cmd_run(args) -> int:
    config = Config.load(args.config)
    if args.rig == "sim":                                      # no real camera to settle
        config.camera_warmup_frames, config.settle_seconds = 0, 0.0
    out = Path(args.out) if args.out else RESULTS_DIR / f"calibration_trials_{dt.date.today():%Y%m%d}.csv"
    display, capture, camcal, release = make_rig(args, config)
    sleep = (lambda s: None) if args.rig == "sim" else time.sleep
    cal = Calibrator(config, display, capture, camcal, sleep=sleep)
    print(f"Logging to {out}")
    try:
        for i in range(1, args.count + 1):
            cal.model = None                       # every run starts from scratch
            run = cal.calibrate()
            row = row_from_run(run, i, args)
            append_row(out, row)
            print(f"run {i:2d}/{args.count}: {run.summary()}")
            sleep(args.pause)
    finally:
        release()
    print(f"\nWrote {args.count} rows to {out}")
    summarize(out, markdown=False)
    return 0


# --------------------------------------------------------------------------
# Summarising
# --------------------------------------------------------------------------

@dataclass
class Summary:
    runs: int
    passed: int
    windows_ok: bool
    worst_window: int
    reductions: list[float]
    times: list[float]
    first_try_detect_rate: float
    errors: dict

    @property
    def pass_rate(self) -> float:
        return self.passed / self.runs if self.runs else 0.0

    @property
    def meets_spec(self) -> bool:
        return (self.windows_ok and all(t < TIME_LIMIT for t in self.times)
                and self.first_try_detect_rate >= DETECT_RATE_REQUIRED)


def summarize_rows(rows: list[dict]) -> Summary:
    passed_flags = [r["passed"] == "yes" for r in rows]
    worst = min((sum(passed_flags[i:i + PASS_WINDOW]) for i in range(max(1, len(rows) - PASS_WINDOW + 1))),
                default=0)
    windows_ok = len(rows) >= PASS_WINDOW and worst >= PASS_REQUIRED
    reductions = [float(r["reduction_percent"]) for r in rows if r["reduction_percent"]]
    times = [float(r["seconds"]) for r in rows if r["seconds"]]
    attempts = []
    for r in rows:
        for key in ("attempts_fit", "attempts_verify_raw", "attempts_verify_corrected"):
            if r[key]:
                attempts.append(int(r[key]))
    first_try = sum(a == 1 for a in attempts) / len(attempts) if attempts else 0.0
    errors: dict = {}
    for r in rows:
        if r["error"]:
            errors[r["error"]] = errors.get(r["error"], 0) + 1
    return Summary(len(rows), sum(passed_flags), windows_ok, worst, reductions, times, first_try, errors)


def format_summary(s: Summary, markdown: bool) -> str:
    def stat(values):
        if not values:
            return "n/a"
        return (f"mean {statistics.mean(values):.1f}, min {min(values):.1f}, "
                f"max {max(values):.1f}, median {statistics.median(values):.1f}")
    lines = [
        f"Runs: {s.runs}, passed: {s.passed} ({100 * s.pass_rate:.0f}%)",
        f"Worst window of {PASS_WINDOW}: {s.worst_window} passed "
        f"({'OK' if s.windows_ok else 'FAIL'}, need {PASS_REQUIRED})",
        f"RMS reduction %: {stat(s.reductions)}",
        f"Time s: {stat(s.times)} (limit {TIME_LIMIT:.0f})",
        f"First-try detection: {100 * s.first_try_detect_rate:.0f}% (need {100 * DETECT_RATE_REQUIRED:.0f}%)",
        f"Specification: {'MET' if s.meets_spec else 'NOT MET'}",
    ]
    if s.errors:
        lines.append("Errors: " + "; ".join(f"{k} x{v}" for k, v in s.errors.items()))
    if markdown:
        return "\n".join(f"- {line}" for line in lines)
    return "\n".join(lines)


def summarize(path: Path, markdown: bool) -> Summary:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    s = summarize_rows(rows)
    print(format_summary(s, markdown))
    return s


def cmd_summarize(args) -> int:
    s = summarize(Path(args.csv), args.markdown)
    return 0 if s.meets_spec else 1


# --------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run N calibrations and log them")
    run.add_argument("--config", default=None)
    run.add_argument("--count", type=int, default=20)
    run.add_argument("--surface", choices=("flat", "curved"), required=True)
    run.add_argument("--distance-cm", type=int, required=True)
    run.add_argument("--lighting", choices=("dark", "dim", "bright"), required=True)
    run.add_argument("--notes", default="")
    run.add_argument("--out", default=None, help="CSV path; default testing/results/calibration_trials_<date>.csv")
    run.add_argument("--pause", type=float, default=2.0, help="seconds between runs")
    run.add_argument("--rig", choices=("hardware", "sim"), default="hardware")
    run.add_argument("--sim-bow", type=float, default=1.0)
    run.add_argument("--sim-blur", type=float, default=1.5)
    run.set_defaults(func=cmd_run)

    summ = sub.add_parser("summarize", help="summarise a results CSV")
    summ.add_argument("csv")
    summ.add_argument("--markdown", action="store_true", help="print as a Markdown list")
    summ.set_defaults(func=cmd_summarize)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
