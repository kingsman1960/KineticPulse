#!/usr/bin/env python3
"""Apply deploy secrets to config.yaml (webrtc block). Called by bootstrap.sh."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml


def _load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        out[key.strip().lstrip("\ufeff")] = val.strip()
    return out


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    secrets = _load_env(root / "deploy" / ".env.deploy")
    jetson_token = secrets["JETSON_SIGNAL_TOKEN"]
    port = secrets.get("SIGNAL_PORT", "8787")

    cfg_path = root / "config.yaml"
    if not cfg_path.exists():
        cfg_path.write_text(
            (root / "config.example.yaml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    raw["webrtc"] = {
        "enabled": True,
        "signaling_url": f"ws://127.0.0.1:{port}/ws",
        "auth_token": jetson_token,
        "session_id_prefix": "kp",
        "always_on": False,
        "connect_timeout_s": 8.0,
        "reconnect_backoff_s": 3.0,
        "max_session_s": 120.0,
        "enable_audio": False,
        "video_bitrate_kbps": 1200,
        "ice_servers": [{"urls": ["stun:stun.l.google.com:19302"]}],
    }
    cfg_path.write_text(
        yaml.safe_dump(raw, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"Updated {cfg_path} (webrtc.enabled=true, signaling_url=ws://127.0.0.1:{port}/ws)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
