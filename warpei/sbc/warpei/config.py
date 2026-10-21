"""Runtime settings (task 2.2).

Everything that changes between the bench, the demo projector, and the
final unit lives here, so swapping a camera, flipping the image, or moving
the calibration file needs no code edit. Values come from, in order:
built-in defaults, an optional JSON file, then command-line overrides.

    cfg = Config.load("config.json")        # missing file -> defaults
    cfg = Config.load(None, camera="1")     # keyword overrides
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .calibration.pattern import PANEL_HEIGHT, PANEL_WIDTH

DEFAULT_CONFIG_PATH = Path.home() / ".warpei" / "config.json"
DEFAULT_CALIBRATION_PATH = Path.home() / ".warpei" / "calibration.json"
DEFAULT_CAMERA_FILE = Path.home() / ".warpei" / "camera.json"


@dataclass
class Config:
    # Panel, in its native orientation.
    panel_width: int = PANEL_WIDTH
    panel_height: int = PANEL_HEIGHT

    # How source content is turned to fit the panel: rotation in degrees
    # clockwise (0, 90, 180, 270), then optional mirror flips.
    source_rotation: int = 90
    source_flip_horizontal: bool = False
    source_flip_vertical: bool = False

    # Camera. "0" is the first camera; a file path plays a video or image sequence.
    camera: str = "0"
    camera_width: int = 1920
    camera_height: int = 1080
    camera_exposure: float | None = None     # None = keep the settled auto value
    camera_warmup_frames: int = 15           # frames to discard after a display change
    pattern_dark_on_light: bool = True

    # Calibration sequence.
    detect_retries: int = 3                  # extra capture attempts per pattern
    settle_seconds: float = 0.4              # wait after showing a pattern before capturing
    calibration_timeout_seconds: float = 180.0
    required_reduction_percent: float = 50.0

    # Display window. offset_x moves the window onto a second screen.
    display_offset_x: int = 0
    display_offset_y: int = 0
    display_fullscreen: bool = True

    # Files.
    calibration_path: str = str(DEFAULT_CALIBRATION_PATH)
    camera_file: str = str(DEFAULT_CAMERA_FILE)
    test_image: str = ""                     # shown in run mode when there is no video input

    extra: dict = field(default_factory=dict)

    # ---- validation and derived values ----------------------------------

    def __post_init__(self) -> None:
        if self.source_rotation not in (0, 90, 180, 270):
            raise ValueError("source_rotation must be 0, 90, 180 or 270")
        if self.panel_width <= 0 or self.panel_height <= 0:
            raise ValueError("panel size must be positive")
        if self.detect_retries < 0:
            raise ValueError("detect_retries must be 0 or more")

    @property
    def panel_size(self) -> tuple[int, int]:
        return (self.panel_width, self.panel_height)

    # ---- loading ---------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path | None = None, **overrides) -> "Config":
        """Defaults, then the JSON file if it exists, then keyword overrides."""
        values: dict = {}
        if path is not None and Path(path).exists():
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            known = {f.name for f in fields(cls)}
            unknown = set(data) - known
            if unknown:
                raise ValueError(f"unknown config keys in {path}: {sorted(unknown)}")
            values.update(data)
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
