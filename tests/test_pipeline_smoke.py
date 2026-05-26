"""End-to-end smoke tests for the Pipeline 2 orchestrator.

Two complementary modes are covered:

1. ``--mock-ble`` (synthetic sensor source):
   bypasses both transports entirely and uses
   :class:`~kineticpulse.sensors.mock.MockSensorClient`. This is the
   fastest path and the one CI usually runs.

2. **Real TCP loopback** (``--mock-ble`` *off*, ``transport: tcp``):
   the orchestrator opens a real TCP server on ``127.0.0.1`` and we
   connect a tiny coroutine that plays the wristband, pushing
   newline-delimited JSON for ~1 s. This catches anything that depends
   on actual stream framing across the orchestrator + sensor server +
   fusion engine.

Every smoke test sets:

* ``--no-camera``   -> skip OpenCV capture and the trained detector /
  pose models (must run on a machine without a webcam, GPU, or
  trained checkpoint).
* ``--mock-stt``    -> canned STT result, no microphone access.
* ``--max-runtime-s`` small -> orchestrator self-terminates quickly.

Each test passes when ``run()`` returns ``0`` within the outer asyncio
timeout without raising.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _free_tcp_port() -> int:
    """Ask the kernel for an unused TCP port and release it immediately."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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
  transport: tcp
  tcp_host: "127.0.0.1"
  tcp_port: 0                # filled in per-test; keep schema-valid here
  tcp_idle_timeout_s: 5.0
  mac: null
  has_accelerometer: true    # let the mock emit accel events for the fusion loop
  has_ppg_raw: false         # smoke test uses pre-computed HR (BPM)
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


def _make_args(
    config_path: Path,
    scenario: str,
    max_runtime_s: float,
    *,
    mock_ble: bool = True,
) -> argparse.Namespace:
    return argparse.Namespace(
        config=config_path,
        mock_ble=mock_ble,
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


def test_pipeline_smoke_real_tcp_transport(tmp_path: Path) -> None:
    """Run the orchestrator with the real TCP server (mock_ble=False), and
    drive it from a tiny in-process 'wristband' that pushes JSON lines.

    This is the closest analogue to the production data path we can run
    without firmware: the whole pipeline (TcpSensorServer -> events queue
    -> fusion engine -> dispatch worker) is exercised with real socket
    framing.
    """
    config_path = tmp_path / "smoke_tcp.yaml"
    port = _free_tcp_port()
    cfg_text = MINIMAL_CONFIG.replace("tcp_port: 0", f"tcp_port: {port}")
    config_path.write_text(cfg_text, encoding="utf-8")

    args = _make_args(
        config_path, scenario="resting", max_runtime_s=2.5, mock_ble=False,
    )

    async def _wristband_emulator() -> None:
        """Connect to the orchestrator's TCP server and stream a few events."""
        # Give the orchestrator a moment to bind the listening socket.
        for _ in range(50):
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                break
            except OSError:
                await asyncio.sleep(0.05)
        else:
            raise RuntimeError(f"Could not connect to orchestrator TCP server on :{port}")

        try:
            writer.write((json.dumps(
                {"type": "hello", "device": "smoke-test", "fw": "0.0.1"}
            ) + "\n").encode("utf-8"))
            for i in range(8):
                writer.write((json.dumps(
                    {"type": "hr", "bpm": 72 + (i % 3)}
                ) + "\n").encode("utf-8"))
                writer.write((json.dumps(
                    {"type": "accel", "ax": 0.0, "ay": 0.0, "az": 1.0}
                ) + "\n").encode("utf-8"))
                await writer.drain()
                await asyncio.sleep(0.1)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _runner() -> int:
        from kineticpulse.main import run
        # Run the orchestrator and the emulator concurrently; the orchestrator
        # owns the deadline (--max-runtime-s) so the emulator just feeds it
        # for a bit and exits.
        emulator = asyncio.create_task(_wristband_emulator())
        try:
            return await asyncio.wait_for(run(args), timeout=12.0)
        finally:
            emulator.cancel()
            try:
                await emulator
            except (asyncio.CancelledError, Exception):
                pass

    exit_code = asyncio.run(_runner())
    assert exit_code == 0
