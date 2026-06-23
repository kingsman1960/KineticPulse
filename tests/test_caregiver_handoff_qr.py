"""Caregiver handoff JSON / QR payload shape."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_caregiver_config_qr_v1_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "deploy").mkdir(parents=True)
        (root / "deploy" / "handoff").mkdir(parents=True)
        (root / "deploy" / ".env.deploy").write_text(
            "JETSON_SIGNAL_TOKEN=j\nCAREGIVER_SIGNAL_TOKEN=care-secret\n"
            "SIGNAL_PORT=8787\nKINETICPULSE_LAN_IP=192.168.1.1\n",
            encoding="utf-8",
        )
        script = REPO / "deploy" / "scripts" / "write_caregiver_handoff.py"
        subprocess.run(
            [sys.executable, str(script), str(root), "100.64.0.5"],
            check=True,
        )
        raw = (root / "deploy" / "handoff" / "caregiver-config.json").read_text(encoding="utf-8")
        obj = json.loads(raw)
        assert obj["v"] == 1
        assert obj["signalingHttpBase"] == "http://100.64.0.5:8787"
        assert obj["signalingWsBase"] == "ws://100.64.0.5:8787/ws"
        assert obj["caregiverToken"] == "care-secret"
