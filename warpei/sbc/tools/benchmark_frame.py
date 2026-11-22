"""Per-stage frame timing (task 4.4, Report 10.3).

Runs the real pipeline stages on N frames and prints mean and worst-case
milliseconds for each: capture dequeue, prepare (rotate/scale/convert),
texture upload + draw, and the total. Also runs the CPU reference remap for
comparison. With a GL context (EGL on the board or Mesa on a PC) it uses
the GPU; without one, GPU rows are skipped.

    python tools/benchmark_frame.py --frames 600 --source 2        # live dongle
    python tools/benchmark_frame.py --frames 600 --synthetic       # no hardware
    python tools/benchmark_frame.py ... --csv ../testing/results/frame_timing.csv
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import platform
import sys
import time
from pathlib import Path

import cv2
import numpy as np

SBC_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SBC_ROOT))

from warpei import storage                                        # noqa: E402
from warpei.calibration import pattern                            # noqa: E402
from warpei.calibration.solve import solve_warp                   # noqa: E402
from warpei.config import Config                                  # noqa: E402
from warpei.video import reference                                # noqa: E402
from warpei.video.capture import open_source                      # noqa: E402


def synthetic_model(panel):
    """A mild warp so the shader does real work."""
    p = pattern.grid_points(panel[0], panel[1])
    c = p * 0.2 + np.array([300.0, 40.0])
    c[:, 0] += 8.0 * ((p[:, 1] - panel[1] / 2) / (panel[1] / 2)) ** 2
    return solve_warp(p, c, panel)


def stats(ms: list[float]) -> tuple[float, float, float]:
    a = np.asarray(ms)
    return float(a.mean()), float(np.percentile(a, 99)), float(a.max())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=None)
    ap.add_argument("--frames", type=int, default=600)
    ap.add_argument("--source", default="2", help="capture dongle index or video file")
    ap.add_argument("--synthetic", action="store_true", help="use a generated 1080p frame instead of a capture")
    ap.add_argument("--calibration", default=None, help="calibration JSON to use; default synthetic model")
    ap.add_argument("--csv", default=None, help="append one row per stage to this CSV")
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    cfg = Config.load(args.config)
    panel = cfg.panel_size
    if args.calibration:
        model = storage.load(args.calibration).warp
    else:
        model = synthetic_model(panel)

    cap = None
    if not args.synthetic:
        cap = open_source(args.source, 1920, 1080)
        if not cap.isOpened():
            print(f"source {args.source} not available; using --synthetic")
            cap = None
    synth = np.random.default_rng(0).integers(0, 255, (1080, 1920, 3), np.uint8)

    gpu = None
    try:
        from warpei.video.renderer import OffscreenRenderer
        gpu = OffscreenRenderer(panel)
        gpu.warp.set_model(model)
        print("GL:", gpu.ctx.info.get("GL_RENDERER"), gpu.ctx.info.get("GL_VERSION"))
    except Exception as exc:
        print(f"no GL context ({exc}); GPU stages skipped")

    maps = reference.build_maps(model)
    t = {"capture": [], "prepare": [], "gpu_upload_draw": [], "gpu_total": [], "cpu_remap": []}
    print(f"running {args.frames} frames on {platform.machine()} ...")
    for i in range(args.frames):
        t0 = time.perf_counter()
        if cap is not None:
            ok, frame = cap.read()
            if not ok:
                print("capture ended early"); break
        else:
            frame = synth
        t1 = time.perf_counter()
        panel_bgr = reference.prepare_source(frame, panel, cfg.source_rotation, False, cfg.source_flip_vertical)
        rgb = cv2.cvtColor(panel_bgr, cv2.COLOR_BGR2RGB)
        t2 = time.perf_counter()
        if gpu is not None:
            gpu.warp.upload(rgb); gpu.warp.draw(); gpu.ctx.finish()
        t3 = time.perf_counter()
        if i % 10 == 0:                                          # CPU path is slow; sample it
            reference.warp_image(panel_bgr, maps)
            t["cpu_remap"].append((time.perf_counter() - t3) * 1000)
        t["capture"].append((t1 - t0) * 1000)
        t["prepare"].append((t2 - t1) * 1000)
        if gpu is not None:
            t["gpu_upload_draw"].append((t3 - t2) * 1000)
            t["gpu_total"].append((t3 - t0) * 1000)

    print(f"\n{'stage':18} {'mean ms':>9} {'p99 ms':>9} {'worst ms':>9}")
    rows = []
    for stage, ms in t.items():
        if not ms:
            continue
        m, p99, w = stats(ms)
        print(f"{stage:18} {m:9.2f} {p99:9.2f} {w:9.2f}")
        rows.append((stage, m, p99, w))
    means = {r[0]: r[1] for r in rows}
    if "gpu_total" in means:
        m = means["gpu_total"]
        print(f"\nGPU path sustains about {1000 / m:.0f} fps per frame budget "
              f"({'OK' if m < 33.3 else 'BELOW'} 30 fps target)")
    if args.csv:
        path = Path(args.csv); new = not path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["timestamp", "machine", "source", "frames", "stage", "mean_ms", "p99_ms", "worst_ms", "notes"])
            for stage, m, p99, worst in rows:
                w.writerow([dt.datetime.now().isoformat(timespec="seconds"), platform.machine(),
                            "synthetic" if cap is None else args.source, args.frames, stage,
                            f"{m:.3f}", f"{p99:.3f}", f"{worst:.3f}", args.notes])
        print(f"appended to {path}")
    if cap is not None:
        cap.release()
    if gpu is not None:
        gpu.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
