"""Boot sequence:
  1. load config and the last calibration (if any)
  2. open the capture dongle, the calibration camera, the panel (GL) and the UART link
  3. run the video pipeline until stopped

Events from the ESP32 (over UART):
  CAL_START  -> pause video, run the calibrator on the panel, resume; send READY or CAL_ERROR
  CAL_ABORT  -> abort a running calibration (checked between its steps)
  FLIP       -> toggle the mirror flag in the shader and remember it

Run:
    python -m warpei.main --config /home/rock/.warpei/config.json
    python -m warpei.main --no-uart --windowed          # laptop bring-up
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
import time

import cv2
import numpy as np

from . import storage
from .app import Calibrator, CalibrationError, OpenCVCamera, State, load_camera_calibration
from .calibration import pattern
from .config import Config
from .link import protocol as P
from .link.uart import UartLink, open_serial
from .video import reference
from .video.capture import Capture, open_source
from .video.pipeline import Pipeline

log = logging.getLogger("warpei")

CAL_ERROR_CODES = {"DETECT_FAIL": P.CalError.DETECT_FAIL, "ACCURACY": P.CalError.ACCURACY,
                   "TIMEOUT": P.CalError.TIMEOUT, "ABORTED": P.CalError.ABORTED, "CAMERA": P.CalError.CAMERA}


def error_code_for(message: str) -> int:
    for name, code in CAL_ERROR_CODES.items():
        if message.startswith(name):
            return code
    return P.CalError.CAMERA if "no frame" in message else P.CalError.DETECT_FAIL


class RendererDisplay:
    """Adapts the GL renderer to the Calibrator's display(image_bgr) callback."""

    def __init__(self, renderer):
        self.renderer = renderer

    def __call__(self, image_bgr: np.ndarray) -> None:
        self.renderer.warp.set_model(None)         # patterns are shown unwarped
        self.renderer.render(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB))


class Application:
    def __init__(self, config: Config, renderer, capture: Capture, camera, link: UartLink | None):
        self.config = config
        self.renderer = renderer
        self.capture = capture
        self.link = link
        self.pipeline = Pipeline(config, capture, renderer, status_lines=self.status_lines)
        self.calibrator = Calibrator(config, RendererDisplay(renderer), camera, load_camera_calibration(config))
        self.calibrator.flip = self.pipeline.flip
        self._abort = threading.Event()
        self._cal_request = threading.Event()
        self._stop = threading.Event()
        self.calibrator.on_state_change(self._on_cal_state)
        if self.calibrator.load_saved():
            self.pipeline.set_model(self.calibrator.model)
            self.pipeline.set_flip(self.calibrator.flip)
        self._announce()

    # ---- state reporting ---------------------------------------------------

    @property
    def app_state(self) -> int:
        if self.calibrator.state in (State.PROJECT_PATTERN, State.CAPTURE, State.SOLVE, State.VERIFY):
            return P.AppState.CALIBRATING
        if self.calibrator.state == State.FAILED and self.pipeline.model is None:
            return P.AppState.ERROR
        if not self.capture.has_source:
            return P.AppState.NO_SOURCE
        return P.AppState.WARPED if self.pipeline.model is not None else P.AppState.PASSTHROUGH

    def _announce(self) -> None:
        if self.link:
            self.link.send_state(self.app_state)

    def _on_cal_state(self, state: State) -> None:
        self._announce()

    def status_lines(self) -> list[str]:
        lines = ["no video input: connect HDMI"]
        if self.link:
            lines.append(self.link.status_text())
        if self.pipeline.model is None:
            lines.append("not calibrated: hold CALIBRATE")
        elif self.calibrator.last_run and not self.calibrator.last_run.error:
            r = self.calibrator.last_run
            lines.append(f"calibrated: {r.reduction_percent:.0f}% reduction")
        if self.calibrator.last_run and self.calibrator.last_run.error:
            lines.append("last calibration: " + self.calibrator.last_run.error.split(":")[0])
        return lines

    # ---- UART events -------------------------------------------------------

    def on_message(self, msg) -> None:
        if msg.id == P.MSG_CAL_START:
            self._cal_request.set()
        elif msg.id == P.MSG_CAL_ABORT:
            self._abort.set()
        elif msg.id == P.MSG_FLIP:
            self.pipeline.set_flip(bool(msg.flip))
            self.calibrator.flip = bool(msg.flip)
            log.info("flip -> %s", bool(msg.flip))
        elif msg.id == P.MSG_FAULT:
            log.warning("controller fault %s at %.1f C", P.FaultCode.NAMES.get(msg.fault_code), msg.object_c_x10 / 10)
        elif msg.id == P.MSG_HEARTBEAT:
            pass
        else:
            log.debug("message %s %s", msg.name, msg.values)

    # ---- calibration -----------------------------------------------------------

    def run_calibration(self) -> None:
        self.pipeline.paused = True
        self._abort.clear()
        try:
            run = self.calibrator.calibrate()
        finally:
            self.pipeline.paused = False
        if run.error:
            if self.link:
                self.link.send_cal_error(error_code_for(run.error))
        else:
            self.pipeline.set_model(self.calibrator.model)
            if self.link:
                self.link.send_ready(run.rms_before, run.rms_after, run.reduction_percent)
        self._announce()

    # ---- main loop -------------------------------------------------------------

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        if self.link:
            self.link.start()
        last_announce = time.monotonic()
        while not self._stop.is_set():
            if self._cal_request.is_set():
                self._cal_request.clear()
                self.run_calibration()
            self.pipeline.step()
            if hasattr(self.renderer, "poll_quit") and self.renderer.poll_quit():
                break
            if time.monotonic() - last_announce > 2.0:    # keep the controller's view current
                self._announce()
                last_announce = time.monotonic()


def build(args) -> Application:
    config = Config.load(args.config, camera=args.camera,
                         display_fullscreen=False if args.windowed else None)
    from .video.renderer import WindowRenderer
    renderer = WindowRenderer(config.panel_size, fullscreen=config.display_fullscreen)
    log.info("GL: %s", renderer.ctx.info.get("GL_RENDERER"))
    src = open_source(args.video_source, 1920, 1080)
    if not src.isOpened():
        log.warning("video source %s not available; status card only", args.video_source)
    capture = Capture(src, no_source_seconds=config.extra.get("no_source_seconds", 2.0)).start()
    camera = OpenCVCamera(config)
    link = None
    if not args.no_uart:
        try:
            link = UartLink(open_serial(args.uart))
        except Exception as exc:
            log.error("UART %s unavailable: %s (running without controller)", args.uart, exc)
    app = Application(config, renderer, capture, camera, link)
    if link:
        link.on_message = app.on_message
    return app


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None)
    parser.add_argument("--camera", default=None, help="calibration camera index")
    parser.add_argument("--video-source", default="2", help="capture dongle index or file")
    parser.add_argument("--uart", default="/dev/ttyS2")
    parser.add_argument("--no-uart", action="store_true")
    parser.add_argument("--windowed", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app = build(args)
    signal.signal(signal.SIGTERM, lambda *_: app.stop())
    signal.signal(signal.SIGINT, lambda *_: app.stop())
    try:
        app.run()
    finally:
        app.capture.stop()
        if app.link:
            app.link.stop()
        app.renderer.release()


if __name__ == "__main__":
    main()
