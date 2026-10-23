"""Task 3.2: trial logging and summary."""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "testing" / "scripts" / "run_trials.py"
spec = importlib.util.spec_from_file_location("run_trials", SCRIPT)
run_trials = importlib.util.module_from_spec(spec)
sys.modules["run_trials"] = run_trials
spec.loader.exec_module(run_trials)


def rows(flags, seconds=5.0, attempts=1):
    return [{"passed": "yes" if f else "no", "reduction_percent": "80.0" if f else "20.0",
             "seconds": str(seconds), "attempts_fit": str(attempts),
             "attempts_verify_raw": "1", "attempts_verify_corrected": "1", "error": ""}
            for f in flags]


def test_three_of_five_window():
    s = run_trials.summarize_rows(rows([1, 1, 0, 1, 1, 0, 1, 1, 1, 0]))
    assert s.windows_ok and s.worst_window == 3 and s.meets_spec
    s = run_trials.summarize_rows(rows([1, 1, 0, 0, 1, 0, 1, 1, 1, 1]))   # window 2..6 has 2 passes
    assert not s.windows_ok and s.worst_window == 2 and not s.meets_spec


def test_fewer_than_five_runs_does_not_pass():
    assert not run_trials.summarize_rows(rows([1, 1, 1])).windows_ok


def test_time_and_detection_limits():
    s = run_trials.summarize_rows(rows([1] * 6, seconds=200.0))
    assert not s.meets_spec
    s = run_trials.summarize_rows(rows([1] * 6, attempts=2))      # fit grid needed 2 tries
    assert s.first_try_detect_rate == pytest.approx(2 / 3)
    assert not s.meets_spec


def test_run_sim_writes_csv_and_summary(tmp_path, capsys):
    out = tmp_path / "trials.csv"
    code = run_trials.main(["run", "--rig", "sim", "--count", "5", "--surface", "curved",
                            "--distance-cm", "90", "--lighting", "dim", "--out", str(out),
                            "--pause", "0", "--config", str(tmp_path / "none.json")])
    assert code == 0
    with out.open() as f:
        data = list(csv.DictReader(f))
    assert len(data) == 5
    assert all(r["passed"] == "yes" for r in data)
    assert set(run_trials.FIELDS) == set(data[0].keys())
    assert "Specification: MET" in capsys.readouterr().out
    assert run_trials.main(["summarize", str(out), "--markdown"]) == 0
