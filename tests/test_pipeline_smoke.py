"""End-to-end smoke test for the Pipeline 2 orchestrator.

Launches :func:`kineticpulse.main.run` with all hardware-touching stages
mocked or disabled:

* ``--no-camera``  -> skip OpenCV capture + the trained detector / pose
  models (this test must run in environments without a webcam, GPU,
  or trained checkpoint).
* ``--mock-ble``   -> synthetic accelerometer + heart-rate stream.
* ``--mock-stt``   -> canned STT result, no microphone access.
* ``--max-runtime-s=2`` -> orchestrator self-terminates after 2 seconds.

The test passes when ``run()`` returns ``0`` within the timeout without
raising.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


MINIMAL_CONFIG = """\
camera:
  source: usb
  device: "0"
  width: 640
  height: 480
  fps: 30

detector:
  weights: runs/detect/kp_v2_4cls/weights/best.pt
  conf: 0.5
  iou: 0.45
  imgsz: 640
  device: cpu

pose:
  enabled: false             # pose isn't exercised here; --no-camera skips capture too
  weights: yolov8n-pose.pt
  conf: 0.5
  imgsz: 640
  device: cpu

temporal:
  enabled: true
  window_size: 30
  stride: 5

wristband:
  mac: null
  has_accelerometer: true    # let the mock emit accel events for the fusion loop
  has_ppg_raw: false         # smoke test uses the standard HR characteristic path
  ppg_sample_rate_hz: 100

thresholds:
  hr_resting_low: 50
  hr_resting_high: 100
  hr_panic_low: 100
  hr_panic_high: 130
  hr_seizure_low: 130
  hr_seizure_high: 160
  pulse_loss_timeout_s: 3.0
  impact_g_threshold: 3.0
  tremor_band_hz: [3.0, 8.0]
  tremor_min_duration_s: 2.0

voice:
  enabled: true
  verify_timeout_s: 1.0
  prompt_text: "smoke test"
  distress_words: ["help"]
  safe_words: ["i am fine"]
  stt_model: small.en
  stt_device: cpu

alerts:
  subject_id: smoke-subject
  location: smoke-test
  webhooks: []               # no outbound HTTP from this test

webrtc:
  enabled: false
  signaling_url: null
  always_on: false

logging:
  level: WARNING
  json: false
"""


def _make_args(config_path: Path, scenario: str, max_runtime_s: float) -> argparse.Namespace:
    return argparse.Namespace(
        config=config_path,
        mock_ble=True,
        mock_ble_scenario=scenario,
        mock_stt=True,
        mock_stt_response="i am fine",
        no_camera=True,
        max_runtime_s=max_runtime_s,
    )


def _run_with_timeout(args: argparse.Namespace, timeout_s: float) -> int:
    """Run the orchestrator with an outer asyncio timeout as a belt-and-braces
    against the in-process ``--max-runtime-s`` failing for any reason."""
    from kineticpulse.main import run

    async def _runner() -> int:
        return await asyncio.wait_for(run(args), timeout=timeout_s)

    return asyncio.run(_runner())


def test_pipeline_smoke_resting_scenario(tmp_path: Path) -> None:
    """Telemetry-only run with the resting mock should idle and exit cleanly."""
    config_path = tmp_path / "smoke.yaml"
    config_path.write_text(MINIMAL_CONFIG, encoding="utf-8")

    args = _make_args(config_path, scenario="resting", max_runtime_s=2.0)
    exit_code = _run_with_timeout(args, timeout_s=10.0)
    assert exit_code == 0


def test_pipeline_smoke_standard_fall_scenario(tmp_path: Path) -> None:
    """Mock 'fall_a_standard' scenario should also exit cleanly, exercising
    the Tier-1 voice-verify branch (mock STT replies 'i am fine' so no
    webhook ever fires - the empty webhooks list is the second safety net).
    """
    config_path = tmp_path / "smoke.yaml"
    config_path.write_text(MINIMAL_CONFIG, encoding="utf-8")

    args = _make_args(config_path, scenario="fall_a_standard", max_runtime_s=2.5)
    exit_code = _run_with_timeout(args, timeout_s=12.0)
    assert exit_code == 0
