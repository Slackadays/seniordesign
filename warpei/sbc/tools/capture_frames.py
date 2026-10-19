"""Capture test photos of the calibration grid for sbc/tests/data/.

Each saved photo is named  <surface>_<distance>cm_<lighting>_<nn>.png
(for example  curved_090cm_dim_03.png)  and gets a row in the data set
README, so the file name and the README always agree.

Typical use, from the sbc/ folder:
    python tools/capture_frames.py --surface flat   --distance-cm 90  --lighting dim
    python tools/capture_frames.py --surface curved --distance-cm 120 --lighting dim
    python tools/capture_frames.py --check

In the preview window: SPACE saves a photo, Q or ESC quits.
"""

from __future__ import annotations

import argparse
import datetime
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

import cv2

SBC_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = SBC_ROOT / "tests" / "data"

# Live "grid found" feedback is optional; capture still works without it.
sys.path.insert(0, str(SBC_ROOT))
try:
    from warpei.calibration.detect import detect_grid
except Exception:  # package not importable: run without the detection hint
    detect_grid = None

SURFACES = ("flat", "curved")
LIGHTING = ("dark", "dim", "bright")
NAME_RE = re.compile(r"^(flat|curved)_(\d{3})cm_(dark|dim|bright)_(\d{2})\.png$")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp"}
MIN_PER_SURFACE = 10

README_HEADER = """# Calibration test images

Photos of the 4 x 11 asymmetric circle grid, used to develop and test
`warpei/calibration/`. Captured with `tools/capture_frames.py`, which adds
one row here per photo. Files are stored through Git LFS.

File name format: `<surface>_<distance>cm_<lighting>_<nn>.png`

| File | Surface | Distance (cm) | Lighting | Resolution | Exposure | White balance | Grid found at capture | Notes | Captured |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
"""


# --------------------------------------------------------------------------
# Camera
# --------------------------------------------------------------------------

def open_camera(source: str, width: int, height: int) -> cv2.VideoCapture:
    """Open a camera by index, or a video file / image sequence by path."""
    if source.isdigit():
        index = int(source)
        if platform.system() == "Linux":
            cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
            # USB 2.0 cameras only reach 1080p at full frame rate in MJPEG.
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        else:
            cap = cv2.VideoCapture(index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    else:
        cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit(f"Could not open camera or file '{source}'.")
    return cap


def lock_settings(cap: cv2.VideoCapture, exposure: float | None,
                  warmup_frames: int = 30) -> dict[str, str]:
    """Let auto-exposure settle, then freeze exposure, white balance and focus.

    Returns a description of what was actually locked. Not every camera and
    operating system allows this (macOS generally does not through OpenCV),
    so the result is reported and written to the README instead of assumed.
    """
    for _ in range(warmup_frames):
        cap.read()

    status: dict[str, str] = {}
    is_linux = platform.system() == "Linux"

    # Exposure. V4L2 uses 1 for manual; other backends use 0.25.
    settled = cap.get(cv2.CAP_PROP_EXPOSURE)
    manual_flag = 1 if is_linux else 0.25
    accepted = cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, manual_flag)
    target = exposure if exposure is not None else settled
    accepted = cap.set(cv2.CAP_PROP_EXPOSURE, target) and accepted
    is_manual = abs(cap.get(cv2.CAP_PROP_AUTO_EXPOSURE) - manual_flag) < 1e-6
    if accepted and is_manual:
        status["exposure"] = f"locked ({cap.get(cv2.CAP_PROP_EXPOSURE):g})"
    else:
        status["exposure"] = "auto (not lockable)"

    # White balance.
    accepted = cap.set(cv2.CAP_PROP_AUTO_WB, 0)
    if accepted and cap.get(cv2.CAP_PROP_AUTO_WB) == 0:
        status["white_balance"] = "locked"
    else:
        status["white_balance"] = "auto (not lockable)"

    # Focus (harmless on a manual-focus lens).
    accepted = cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
    status["focus"] = "locked" if accepted else "fixed or not lockable"
    return status


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------

def file_prefix(surface: str, distance_cm: int, lighting: str) -> str:
    return f"{surface}_{distance_cm:03d}cm_{lighting}_"


def next_index(out_dir: Path, prefix: str) -> int:
    """Return the next free two-digit index for this prefix (starts at 1)."""
    used = [int(p.stem[-2:]) for p in out_dir.glob(prefix + "[0-9][0-9].png")]
    return max(used, default=0) + 1


def append_readme_row(out_dir: Path, cells: list[str]) -> None:
    readme = out_dir / "README.md"
    if not readme.exists():
        readme.write_text(README_HEADER, encoding="utf-8")
    with readme.open("a", encoding="utf-8") as handle:
        handle.write("| " + " | ".join(cells) + " |\n")


def save_photo(frame, out_dir: Path, args, lock: dict[str, str]) -> Path:
    """Write one photo and its README row. Returns the saved path."""
    prefix = file_prefix(args.surface, args.distance_cm, args.lighting)
    index = next_index(out_dir, prefix)
    if index > 99:
        raise SystemExit(f"Already 99 photos named {prefix}NN.png; use other settings.")
    path = out_dir / f"{prefix}{index:02d}.png"
    if not cv2.imwrite(str(path), frame):
        raise SystemExit(f"Could not write {path}")

    if detect_grid is None:
        found = "not checked"
    else:
        found = "yes" if detect_grid(frame).found else "no"

    height, width = frame.shape[:2]
    append_readme_row(out_dir, [
        f"`{path.name}`", args.surface, str(args.distance_cm), args.lighting,
        f"{width} x {height}", lock["exposure"], lock["white_balance"], found,
        args.notes.replace("|", "/"),
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    ])
    return path


# --------------------------------------------------------------------------
# Capture loops
# --------------------------------------------------------------------------

def capture_interactive(cap, out_dir: Path, args, lock: dict[str, str]) -> int:
    """Preview window; SPACE saves, Q or ESC quits. Returns photos saved."""
    saved = 0
    frame_number = 0
    hint = ""
    window = "Warpei capture  (SPACE = save, Q = quit)"
    while True:
        ok, frame = cap.read()
        if not ok:
            print("Camera stopped delivering frames.")
            break
        frame_number += 1

        # Detection is slow at 1080p, so refresh the hint twice a second.
        if detect_grid is not None and frame_number % 15 == 1:
            hint = "grid FOUND" if detect_grid(frame).found else "grid not found"

        scale = min(1.0, 1280 / frame.shape[1])
        preview = cv2.resize(frame, None, fx=scale, fy=scale)
        label = f"{args.surface} {args.distance_cm} cm {args.lighting}   saved {saved}   {hint}"
        cv2.putText(preview, label, (16, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4)
        cv2.putText(preview, label, (16, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.imshow(window, preview)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord(" "):
            path = save_photo(frame, out_dir, args, lock)   # raw frame, no overlay
            saved += 1
            print(f"Saved {path.name}")
    cv2.destroyAllWindows()
    return saved


def capture_automatic(cap, out_dir: Path, args, lock: dict[str, str]) -> int:
    """No window: save --count photos, --interval seconds apart."""
    saved = 0
    for _ in range(args.count):
        ok, frame = cap.read()
        if not ok:
            print("Camera stopped delivering frames.")
            break
        path = save_photo(frame, out_dir, args, lock)
        saved += 1
        print(f"Saved {path.name}")
        time.sleep(args.interval)
    return saved


# --------------------------------------------------------------------------
# Acceptance check for task 1.1
# --------------------------------------------------------------------------

def _lfs_tracked(path: Path) -> bool | None:
    """True/False if git can tell whether the file goes through LFS, else None."""
    try:
        result = subprocess.run(["git", "check-attr", "filter", "--", path.name],
                                cwd=path.parent, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip().endswith("filter: lfs")


def check_data_set(out_dir: Path) -> bool:
    """Print a report and return True when the task 1.1 criteria are met."""
    images = sorted(p for p in out_dir.iterdir()
                    if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES) if out_dir.exists() else []
    readme = out_dir / "README.md"
    readme_text = readme.read_text(encoding="utf-8") if readme.exists() else ""

    counts = {surface: 0 for surface in SURFACES}
    bad_names, not_in_readme, not_lfs = [], [], []
    for path in images:
        match = NAME_RE.match(path.name)
        if not match:
            bad_names.append(path.name)
            continue
        counts[match.group(1)] += 1
        if path.name not in readme_text:
            not_in_readme.append(path.name)
        if _lfs_tracked(path) is False:
            not_lfs.append(path.name)

    print(f"Data set: {out_dir}")
    for surface in SURFACES:
        mark = "ok" if counts[surface] >= MIN_PER_SURFACE else "NEED MORE"
        print(f"  {surface:<7} {counts[surface]:>3} of {MIN_PER_SURFACE} required   {mark}")
    for title, names in (("File names that do not state surface and distance", bad_names),
                         ("Photos missing from README.md", not_in_readme),
                         ("Photos not routed through Git LFS", not_lfs)):
        if names:
            print(f"  {title}: {', '.join(names)}")

    passed = (all(counts[s] >= MIN_PER_SURFACE for s in SURFACES)
              and not bad_names and not not_in_readme and not not_lfs)
    print("PASS" if passed else "NOT YET")
    return passed


# --------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="report whether the data set meets the task 1.1 criteria, then exit")
    parser.add_argument("--surface", choices=SURFACES)
    parser.add_argument("--distance-cm", type=int, help="camera-to-surface distance, 1 to 999")
    parser.add_argument("--lighting", choices=LIGHTING)
    parser.add_argument("--notes", default="", help="free text for the README row")
    parser.add_argument("--camera", default="0", help="camera index, or a video file path")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--exposure", type=float, default=None,
                        help="manual exposure value; default keeps the settled auto value")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--no-preview", action="store_true",
                        help="save --count photos automatically, with no window")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()

    if args.check:
        sys.exit(0 if check_data_set(args.out) else 1)

    if not (args.surface and args.distance_cm and args.lighting):
        parser.error("--surface, --distance-cm and --lighting are required to capture")
    if not 1 <= args.distance_cm <= 999:
        parser.error("--distance-cm must be between 1 and 999")

    args.out.mkdir(parents=True, exist_ok=True)
    cap = open_camera(args.camera, args.width, args.height)
    lock = lock_settings(cap, args.exposure)

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Resolution     {actual_w} x {actual_h}"
          + ("" if (actual_w, actual_h) == (args.width, args.height) else "   (requested size not available)"))
    print(f"Exposure       {lock['exposure']}")
    print(f"White balance  {lock['white_balance']}")
    print(f"Focus          {lock['focus']}")

    try:
        if args.no_preview:
            saved = capture_automatic(cap, args.out, args, lock)
        else:
            saved = capture_interactive(cap, args.out, args, lock)
    finally:
        cap.release()
    print(f"Saved {saved} photo(s) to {args.out}")


if __name__ == "__main__":
    main()
