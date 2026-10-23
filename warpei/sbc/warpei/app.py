"""Calibration state machine and demo application (tasks 2.3 and 2.4).

States:  IDLE -> PROJECT_PATTERN -> CAPTURE -> SOLVE -> VERIFY -> RUN
                      ^                 |                   |
                      +---- retry ------+        FAILED <---+ (falls back to last saved)

The Calibrator class is independent of any window or camera, it is given a
`display(image)` function and a `capture()` function

    python -m warpei.app                     # defaults, camera 0
    python -m warpei.app --camera 1 --config config.json

Keys in output window: C calibrate, T toggle correction, R show raw
pattern, S save a screenshot, Q quit.
"""

from __future__ import annotations

import argparse
import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

import cv2
import numpy as np

from . import storage
from .calibration import pattern, validate
from .calibration.detect import DetectionResult, detect_grid
from .calibration.solve import WarpModel, solve_warp
from .calibration.undistort import CameraCalibration, identity_calibration
from .config import Config
from .video import reference

log = logging.getLogger("warpei")


class State(enum.Enum):
    IDLE = "idle"
    PROJECT_PATTERN = "project_pattern"
    CAPTURE = "capture"
    SOLVE = "solve"
    VERIFY = "verify"
    RUN = "run"
    FAILED = "failed"


class CalibrationError(Exception):
    pass


@dataclass
class CalibrationRun:
    """Everything one calibration attempt produced, for logs and the report."""
    model: WarpModel | None = None
    rms_before: float | None = None
    rms_after: float | None = None
    reduction_percent: float | None = None
    passed: bool = False
    seconds: float = 0.0
    attempts: dict = field(default_factory=dict)     # pattern name -> captures used
    error: str = ""

    def summary(self) -> str:
        if self.error:
            return f"FAILED after {self.seconds:.1f} s: {self.error}"
        return (f"RMS before {self.rms_before:.2f} px, after {self.rms_after:.2f} px, "
                f"reduction {self.reduction_percent:.1f}% "
                f"({'PASS' if self.passed else 'FAIL'}), {self.seconds:.1f} s")


class Calibrator:
    """Runs the calibration sequence through injected display and capture functions."""

    def __init__(self, config: Config,
                 display: Callable[[np.ndarray], None],
                 capture: Callable[[], np.ndarray | None],
                 camera: CameraCalibration | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.config = config
        self.display = display
        self.capture = capture
        self.camera = camera or identity_calibration(config.camera_width, config.camera_height)
        self.sleep = sleep
        self.state = State.IDLE
        self.model: WarpModel | None = None
        self.last_run: CalibrationRun | None = None
        self._listeners: list[Callable[[State], None]] = []

    # ---- state ------------------------------------------------------------

    def on_state_change(self, fn: Callable[[State], None]) -> None:
        self._listeners.append(fn)

    def _set(self, state: State) -> None:
        self.state = state
        log.info("state -> %s", state.value)
        for fn in self._listeners:
            fn(state)

    # ---- building blocks --------------------------------------------------

    def _panel_pattern(self, offset=(0.0, 0.0)) -> np.ndarray:
        img = pattern.render_pattern(self.config.panel_width, self.config.panel_height,
                                     dark_on_light=self.config.pattern_dark_on_light,
                                     offset=offset)
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    def _show_and_capture(self, image: np.ndarray, name: str,
                          run: CalibrationRun) -> np.ndarray:
        """Display an image, wait for it to settle, capture until the grid is found."""
        self.display(image)
        self.sleep(self.config.settle_seconds)
        for _ in range(self.config.camera_warmup_frames):
            self.capture()                      # flush frames taken before the change
        for attempt in range(1, self.config.detect_retries + 2):
            frame = self.capture()
            if frame is None:
                raise CalibrationError("camera returned no frame")
            self.camera.check_image_size(frame.shape[1], frame.shape[0])
            result: DetectionResult = detect_grid(frame, dark_on_light=self.config.pattern_dark_on_light)
            run.attempts[name] = attempt
            if result.found:
                log.info("%s: grid found on attempt %d (%s)", name, attempt, result.attempt)
                return self.camera.undistort_points(result.centers)
            log.warning("%s: grid not found (attempt %d, %d blobs)", name, attempt, result.blob_count)
            self.sleep(self.config.settle_seconds)
        raise CalibrationError(f"{name}: grid not found after {self.config.detect_retries + 1} attempts")

    # ---- the sequence -----------------------------------------------------

    def calibrate(self) -> CalibrationRun:
        """Run the full sequence. Never raises; the result's error field says what went wrong."""
        run = CalibrationRun()
        start = time.perf_counter()
        cfg = self.config
        panel_pts = pattern.grid_points(cfg.panel_width, cfg.panel_height)
        shifted_pts = pattern.grid_points(cfg.panel_width, cfg.panel_height, offset=pattern.VERIFY_OFFSET)
        try:
            # 1. Project the fitting grid and measure it.
            self._set(State.PROJECT_PATTERN)
            self._set(State.CAPTURE)
            fit_cam = self._show_and_capture(self._panel_pattern(), "fit grid", run)

            # 2. Solve.
            self._set(State.SOLVE)
            model = solve_warp(panel_pts, fit_cam, cfg.panel_size)
            log.info("solve: homography rms %.2f px, fit rms %.2f px, shrink %.1f%%",
                     model.homography_rms, model.fit_rms, 100 * model.shrink)

            # 3. Verify on the shifted grid: raw ("before") and corrected ("after").
            self._set(State.VERIFY)
            raw_cam = self._show_and_capture(self._panel_pattern(pattern.VERIFY_OFFSET),
                                             "verify raw", run)
            before = validate.uncorrected_error(model, shifted_pts, raw_cam)

            maps = reference.build_maps(model)
            corrected_img = reference.warp_image(self._panel_pattern(pattern.VERIFY_OFFSET), maps)
            corr_cam = self._show_and_capture(corrected_img, "verify corrected", run)
            after = validate.corrected_error(model, shifted_pts, corr_cam)

            run.model = model
            run.rms_before, run.rms_after = before.rms, after.rms
            run.reduction_percent = validate.percent_reduction(before, after)
            run.passed = run.reduction_percent >= cfg.required_reduction_percent
            run.seconds = time.perf_counter() - start
            if run.seconds > cfg.calibration_timeout_seconds:
                raise CalibrationError(f"took {run.seconds:.0f} s, over the {cfg.calibration_timeout_seconds:.0f} s limit")

            # 4. Keep it and save it.
            self.model = model
            self._save(run)
            self._set(State.RUN)
        except CalibrationError as exc:
            run.error = str(exc)
            run.seconds = time.perf_counter() - start
            log.error("calibration failed: %s", exc)
            self._set(State.FAILED)
            if self.model is not None:
                log.info("keeping the previous calibration")
                self._set(State.RUN)
        self.last_run = run
        log.info(run.summary())
        return run

    # ---- persistence --------------------------------------------------------

    def _save(self, run: CalibrationRun) -> None:
        calib = storage.CalibrationFile(warp=run.model, camera=self.camera,
                                        rms_before=run.rms_before, rms_after=run.rms_after,
                                        notes={"reduction_percent": run.reduction_percent,
                                               "passed": run.passed, "seconds": run.seconds})
        storage.save(calib, self.config.calibration_path)
        log.info("saved calibration to %s", self.config.calibration_path)

    def load_saved(self) -> bool:
        """Load the last calibration from disk. Returns True if one was usable."""
        calib = storage.load_or_none(self.config.calibration_path)
        if calib is None or calib.warp is None:
            return False
        if tuple(calib.warp.panel_size) != self.config.panel_size:
            log.warning("saved calibration is for a %sx%s panel, ignoring", *calib.warp.panel_size)
            return False
        self.model = calib.warp
        if calib.camera is not None:
            self.camera = calib.camera
        self._set(State.RUN)
        log.info("loaded calibration from %s (after rms %.2f px)",
                 self.config.calibration_path, calib.rms_after or 0.0)
        return True


# ==========================================================================
# Program: OpenCV window + VideoCapture
# ==========================================================================

WINDOW = "warpei"


class OpenCVDisplay:
    """Full-screen output window, moved by an offset so it lands on the projector."""

    def __init__(self, config: Config):
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        cv2.moveWindow(WINDOW, config.display_offset_x, config.display_offset_y)
        if config.display_fullscreen:
            cv2.setWindowProperty(WINDOW, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        self.last: np.ndarray | None = None

    def __call__(self, image: np.ndarray) -> None:
        self.last = image
        cv2.imshow(WINDOW, image)
        cv2.waitKey(1)


class OpenCVCamera:
    def __init__(self, config: Config):
        src = config.camera
        self.cap = cv2.VideoCapture(int(src)) if src.isdigit() else cv2.VideoCapture(src)
        if not self.cap.isOpened():
            raise SystemExit(f"could not open camera '{src}'")
        if src.isdigit():
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.camera_width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.camera_height)
            if config.camera_exposure is not None:
                self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
                self.cap.set(cv2.CAP_PROP_EXPOSURE, config.camera_exposure)
            self.cap.set(cv2.CAP_PROP_AUTO_WB, 0)

    def __call__(self) -> np.ndarray | None:
        ok, frame = self.cap.read()
        return frame if ok else None

    def release(self) -> None:
        self.cap.release()


def load_camera_calibration(config: Config) -> CameraCalibration:
    try:
        cam = CameraCalibration.load(config.camera_file)
        log.info("camera calibration loaded from %s (rms %.2f px)", config.camera_file,
                 cam.rms_reprojection_error)
        return cam
    except (FileNotFoundError, ValueError, KeyError):
        log.warning("no camera calibration at %s; using no lens correction", config.camera_file)
        return identity_calibration(config.camera_width, config.camera_height)


def run_mode_image(config: Config) -> np.ndarray:
    """What to show in RUN state while there is no live video input (Phase 4)."""
    if config.test_image:
        img = cv2.imread(config.test_image)
        if img is not None:
            return reference.prepare_source(img, config.panel_size, config.source_rotation,
                                            config.source_flip_horizontal, config.source_flip_vertical)
        log.warning("could not read test image %s", config.test_image)
    return reference.test_card(config.panel_size)


def overlay_status(image: np.ndarray, lines: list[str]) -> np.ndarray:
    out = image.copy()
    y = 48
    for line in lines:
        cv2.putText(out, line, (24, y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 5)
        cv2.putText(out, line, (24, y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        y += 40
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None, help="JSON config file")
    parser.add_argument("--camera", default=None)
    parser.add_argument("--calibration-path", default=None)
    parser.add_argument("--camera-file", default=None)
    parser.add_argument("--test-image", default=None)
    parser.add_argument("--display-offset-x", type=int, default=None)
    parser.add_argument("--windowed", action="store_true", help="do not go full screen")
    parser.add_argument("--calibrate-on-start", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    config = Config.load(args.config, camera=args.camera,
                         calibration_path=args.calibration_path, camera_file=args.camera_file,
                         test_image=args.test_image, display_offset_x=args.display_offset_x,
                         display_fullscreen=False if args.windowed else None)

    display = OpenCVDisplay(config)
    camera = OpenCVCamera(config)
    calibrator = Calibrator(config, display, camera, load_camera_calibration(config))
    calibrator.load_saved()

    source = run_mode_image(config)
    maps = reference.build_maps(calibrator.model) if calibrator.model else None
    show_corrected = True
    show_overlay = True
    if args.calibrate_on_start:
        run = calibrator.calibrate()
        maps = reference.build_maps(calibrator.model) if calibrator.model else None

    try:
        while True:
            if calibrator.model is not None and show_corrected:
                frame = reference.warp_image(source, maps)
            else:
                frame = source
            if show_overlay:
                lines = [f"state: {calibrator.state.value}   correction: {'on' if show_corrected and maps is not None else 'off'}"]
                if calibrator.last_run is not None:
                    lines.append(calibrator.last_run.summary())
                lines.append("C calibrate   T toggle   R raw pattern   O overlay   Q quit")
                frame = overlay_status(frame, lines)
            display(frame)

            key = cv2.waitKey(30) & 0xFF
            if key in (ord("q"), 27):
                break
            elif key == ord("c"):
                run = calibrator.calibrate()
                maps = reference.build_maps(calibrator.model) if calibrator.model else None
                print(run.summary())
            elif key == ord("t"):
                show_corrected = not show_corrected
            elif key == ord("o"):
                show_overlay = not show_overlay
            elif key == ord("r"):
                display(calibrator._panel_pattern())
                cv2.waitKey(0)
            elif key == ord("s"):
                name = time.strftime("screenshot_%Y%m%d_%H%M%S.png")
                cv2.imwrite(name, frame)
                print(f"saved {name}")
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
