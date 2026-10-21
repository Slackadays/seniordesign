"""Task 2.2: settings.

Acceptance: changing rotation, flip, or camera needs no code edit; defaults
match the 1440 x 2560 panel.
"""

from __future__ import annotations

import json

import pytest

from warpei.config import Config


def test_defaults_match_panel():
    cfg = Config()
    assert cfg.panel_size == (1440, 2560)
    assert cfg.source_rotation == 90
    assert cfg.camera == "0"


def test_file_and_overrides(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"camera": "2", "source_flip_vertical": True,
                                "display_offset_x": 1920}))
    cfg = Config.load(path, camera="5")
    assert cfg.camera == "5"                 # override beats file
    assert cfg.source_flip_vertical is True  # file beats default
    assert cfg.display_offset_x == 1920
    assert cfg.source_rotation == 90         # default kept


def test_missing_file_gives_defaults(tmp_path):
    assert Config.load(tmp_path / "nope.json") == Config()


def test_none_overrides_are_ignored():
    assert Config.load(None, camera=None).camera == "0"


def test_rejects_bad_values(tmp_path):
    with pytest.raises(ValueError):
        Config(source_rotation=45)
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"not_a_key": 1}))
    with pytest.raises(ValueError):
        Config.load(path)


def test_save_round_trip(tmp_path):
    cfg = Config(camera="3", detect_retries=5)
    cfg.save(tmp_path / "c.json")
    assert Config.load(tmp_path / "c.json") == cfg
