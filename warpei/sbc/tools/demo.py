"""DEMO program (task 3.3).

Shows content on the projector with the correction switchable on and off,
and keeps the before/after numbers on screen. Run from sbc/:

    python tools/demo.py --config configs/demo_projector_1080p.json
    python tools/demo.py --config ... --photo path/to/photo.jpg --calibrate-on-start

KEYS:
    C   run a calibration (counts as one demo cycle)
    T   toggle correction on / off
    1   show the straight-line test card
    2   show the photo given with --photo
    3   show the raw circle grid
    P   save a before/after camera photo pair to demo_captures/
    O   hide / show the overlay text
    Q   quit
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import cv2
import numpy as np

SBC_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SBC_ROOT))

from warpei.app import Calibrator, OpenCVCamera, OpenCVDisplay, load_camera_calibration  # noqa: E402
from warpei.calibration import pattern                                                   # noqa: E402
from warpei.config import Config                                                         # noqa: E402
from warpei.video import reference                                                       # noqa: E402

log = logging.getLogger("warpei.demo")


def big_overlay(image: np.ndarray, lines: list[str]) -> np.ndarray:
    """Large text with a dark band behind it, readable from across a room."""
    out = image.copy()
    h, w = out.shape[:2]
    scale = max(0.8, w / 1600)
    line_h = int(44 * scale)
    band_h = line_h * len(lines) + int(24 * scale)
    cv2.rectangle(out, (0, h - band_h), (w, h), (0, 0, 0), -1)
    y = h - band_h + line_h
    for line in lines:
        cv2.putText(out, line, (int(24 * scale), y), cv2.FONT_HERSHEY_SIMPLEX,
                    scale, (255, 255, 255), max(2, int(2 * scale)), cv2.LINE_AA)
        y += line_h
    return out


def save_pair(display, camera, config, source, maps, out_dir: Path, sleep=time.sleep) -> Path:
    """Photograph the surface with correction off, then on; write them side by side."""
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for corrected in (False, True):
        img = reference.warp_image(source, maps) if (corrected and maps is not None) else source
        display(img)
        sleep(config.settle_seconds)
        for _ in range(config.camera_warmup_frames):
            camera()
        frame = camera()
        if frame is None:
            raise RuntimeError("camera returned no frame")
        label = "correction ON" if corrected else "correction OFF"
        cv2.putText(frame, label, (24, 48), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 6)
        cv2.putText(frame, label, (24, 48), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 2)
        frames.append(frame)
    pair = np.hstack(frames)
    path = out_dir / time.strftime("pair_%Y%m%d_%H%M%S.png")
    cv2.imwrite(str(path), pair)
    return path


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None)
    parser.add_argument("--camera", default=None)
    parser.add_argument("--photo", default=None, help="image to show with key 2")
    parser.add_argument("--windowed", action="store_true")
    parser.add_argument("--calibrate-on-start", action="store_true")
    parser.add_argument("--captures", default="demo_captures", help="folder for before/after pairs")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    config = Config.load(args.config, camera=args.camera,
                         display_fullscreen=False if args.windowed else None)

    display = OpenCVDisplay(config)
    camera = OpenCVCamera(config)
    cal = Calibrator(config, display, camera, load_camera_calibration(config))
    cal.load_saved()

    card = reference.test_card(config.panel_size)
    photo = None
    if args.photo:
        img = cv2.imread(args.photo)
        if img is None:
            print(f"could not read {args.photo}")
        else:
            photo = reference.prepare_source(img, config.panel_size, config.source_rotation,
                                             config.source_flip_horizontal, config.source_flip_vertical)
    grid = cv2.cvtColor(pattern.render_pattern(config.panel_width, config.panel_height), cv2.COLOR_GRAY2BGR)
    sources = {"1": ("test card", card), "2": ("photo", photo if photo is not None else card),
               "3": ("circle grid", grid)}

    maps = reference.build_maps(cal.model) if cal.model else None
    corrected_on = True
    overlay_on = True
    current = "1"
    cycles = 0
    started = time.time()

    def recalibrate():
        nonlocal maps, cycles
        run = cal.calibrate()
        maps = reference.build_maps(cal.model) if cal.model else None
        cycles += 1
        print(f"cycle {cycles}: {run.summary()}")

    if args.calibrate_on_start:
        recalibrate()

    try:
        while True:
            name, source = sources[current]
            frame = reference.warp_image(source, maps) if (corrected_on and maps is not None) else source
            if overlay_on:
                status = "ON" if (corrected_on and maps is not None) else "OFF"
                lines = [f"Warpei   correction {status}   showing: {name}   cycles: {cycles}"]
                if cal.last_run and not cal.last_run.error:
                    r = cal.last_run
                    lines.append(f"RMS before {r.rms_before:.1f} px   after {r.rms_after:.1f} px   "
                                 f"reduction {r.reduction_percent:.0f}%   {r.seconds:.1f} s")
                elif cal.last_run:
                    lines.append(f"last calibration failed: {cal.last_run.error}")
                elif maps is None:
                    lines.append("no calibration yet: press C")
                frame = big_overlay(frame, lines)
            display(frame)

            key = cv2.waitKey(30) & 0xFF
            if key in (ord("q"), 27):
                break
            elif key == ord("c"):
                recalibrate()
            elif key == ord("t"):
                corrected_on = not corrected_on
            elif key == ord("o"):
                overlay_on = not overlay_on
            elif key in (ord("1"), ord("2"), ord("3")):
                current = chr(key)
            elif key == ord("p"):
                path = save_pair(display, camera, config, source, maps, Path(args.captures))
                print(f"saved {path}")
    finally:
        camera.release()
        cv2.destroyAllWindows()
        print(f"demo ran {time.time() - started:.0f} s, {cycles} calibration cycles")


if __name__ == "__main__":
    main()
