"""Save and load the calibration file (task 1.6).

One JSON file holds the warp model, the camera lens calibration, and the
error numbers from the last run. It is written atomically: the data goes to
a temporary file in the same folder, which is then renamed over the old
file. A power cut during the write leaves the previous calibration intact,
because the rename is the only step that touches the real file name.
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .calibration.solve import WarpModel
from .calibration.undistort import CameraCalibration

FORMAT_VERSION = 1


@dataclass
class CalibrationFile:
    warp: WarpModel | None = None
    camera: CameraCalibration | None = None
    rms_before: float | None = None
    rms_after: float | None = None
    saved_at: str = ""
    notes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "format_version": FORMAT_VERSION,
            "saved_at": self.saved_at,
            "warp": self.warp.to_dict() if self.warp else None,
            "camera": self.camera.to_dict() if self.camera else None,
            "rms_before": self.rms_before,
            "rms_after": self.rms_after,
            "notes": dict(self.notes),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CalibrationFile":
        version = d.get("format_version")
        if version != FORMAT_VERSION:
            raise ValueError(f"calibration file format {version} is not supported")
        return cls(
            warp=WarpModel.from_dict(d["warp"]) if d.get("warp") else None,
            camera=CameraCalibration.from_dict(d["camera"]) if d.get("camera") else None,
            rms_before=d.get("rms_before"),
            rms_after=d.get("rms_after"),
            saved_at=d.get("saved_at", ""),
            notes=dict(d.get("notes", {})),
        )


def save(calib: CalibrationFile, path: str | Path) -> None:
    """Write atomically. Either the new file is complete or the old one survives."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not calib.saved_at:
        calib.saved_at = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    text = json.dumps(calib.to_dict(), indent=2)

    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())          # data on disk before the rename
        os.replace(tmp_name, path)             # atomic on POSIX and NTFS
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load(path: str | Path) -> CalibrationFile:
    """Read a calibration file. Raises FileNotFoundError or ValueError."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return CalibrationFile.from_dict(data)


def load_or_none(path: str | Path) -> CalibrationFile | None:
    """Return the saved calibration, or None if there is none or it is unreadable."""
    try:
        return load(path)
    except (FileNotFoundError, ValueError, KeyError, json.JSONDecodeError):
        return None
