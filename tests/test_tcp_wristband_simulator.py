"""Tests for the TCP wristband simulator event shapes."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "tcp_wristband_simulator.py"
spec = importlib.util.spec_from_file_location("tcp_wristband_simulator", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim)


def _events_for(scenario: str):
    with patch.object(sim.time, "sleep", return_value=None), patch.object(
        sim, "monotonic_ts_ms", return_value=123456
    ):
        return list(sim.iter_scenario_events(
            scenario,
            count=4,
            interval_s=0.0,
            include_ppg=True,
        ))


def test_resting_scenario_uses_readme_schema() -> None:
    events = [sim.hello_event()] + _events_for("resting")

    assert events[0] == {
        "type": "hello",
        "device": "esp32-kp-001",
        "fw": "0.1.0",
        "caps": ["hr", "accel", "ppg"],
    }
    assert any(e["type"] == "hr" and "bpm" in e and "ts" in e for e in events)
    assert any(
        e["type"] == "accel"
        and {"ax", "ay", "az", "ts"}.issubset(e.keys())
        for e in events
    )
    assert any(
        e["type"] == "ppg"
        and isinstance(e["ir"], list)
        and isinstance(e["red"], list)
        and len(e["ir"]) == len(e["red"])
        for e in events
    )


def test_standard_fall_includes_impact_and_elevated_hr() -> None:
    events = _events_for("standard_fall")
    hrs = [e["bpm"] for e in events if e["type"] == "hr"]
    accel_peaks = [
        (e["ax"] * e["ax"] + e["ay"] * e["ay"] + e["az"] * e["az"]) ** 0.5
        for e in events
        if e["type"] == "accel"
    ]

    assert max(hrs) >= 108
    assert max(accel_peaks) >= 3.0


def test_pulse_lost_scenario_emits_pulse_lost_event() -> None:
    events = _events_for("pulse_lost")

    assert any(
        e["type"] == "pulse_lost" and e["duration_s"] == 3.0 and "ts" in e
        for e in events
    )


def test_encode_event_is_newline_delimited_utf8_json() -> None:
    encoded = sim.encode_event({"type": "hr", "bpm": 72, "ts": 1})

    assert encoded.endswith(b"\n")
    assert json.loads(encoded.decode("utf-8")) == {"type": "hr", "bpm": 72, "ts": 1}
