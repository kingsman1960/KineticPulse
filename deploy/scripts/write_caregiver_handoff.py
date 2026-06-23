#!/usr/bin/env python3
"""Write caregiver handoff JSON + optional QR PNG for mobile app setup."""
from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path


def _load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        out[key.strip().lstrip("\ufeff")] = val.strip()
    return out


def _write_setup_html(handoff: Path, qr_png: Path, payload: dict[str, str]) -> None:
    if not qr_png.is_file():
        return
    b64 = base64.standard_b64encode(qr_png.read_bytes()).decode("ascii")
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>KineticPulse caregiver setup</title>
<style>body{{font-family:system-ui,sans-serif;max-width:28rem;margin:2rem auto;padding:0 1rem;text-align:center}}
img{{width:min(100%,320px);height:auto}}</style></head><body>
<h1>Caregiver setup QR</h1>
<p>Scan with the KineticPulse mobile app (Tailscale on phone, same tailnet).</p>
<p><img alt="Setup QR" src="data:image/png;base64,{b64}"></p>
<p><small>Signaling: {payload["signalingHttpBase"]}</small></p>
</body></html>
"""
    (handoff / "setup.html").write_text(html, encoding="utf-8")


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    handoff = root / "deploy" / "handoff"
    handoff.mkdir(parents=True, exist_ok=True)

    secrets = _load_env(root / "deploy" / ".env.deploy")
    host = sys.argv[2] if len(sys.argv) > 2 else secrets.get("KINETICPULSE_LAN_IP", "127.0.0.1")
    port = secrets.get("SIGNAL_PORT", "8787")
    token = secrets["CAREGIVER_SIGNAL_TOKEN"]

    payload = {
        "v": 1,
        "signalingHttpBase": f"http://{host}:{port}",
        "signalingWsBase": f"ws://{host}:{port}/ws",
        "caregiverToken": token,
        "iceServersText": "stun:stun.l.google.com:19302",
    }
    json_path = handoff / "caregiver-config.json"
    json_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

    qr_png = handoff / "caregiver-qr.png"
    qr_txt = handoff / "caregiver-qr.txt"
    line = json.dumps(payload, separators=(",", ":"))
    qr_txt.write_text(line + "\n", encoding="utf-8")

    has_qr = False
    try:
        subprocess.run(
            ["qrencode", "-o", str(qr_png), "-t", "PNG", "-s", "8", "-m", "2", line],
            check=True,
            capture_output=True,
        )
        has_qr = True
        print(f"Wrote {qr_png}")
        _write_setup_html(handoff, qr_png, payload)
        print(f"Wrote {handoff / 'setup.html'}")
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("qrencode not available - caregiver-config.json + caregiver-qr.txt only")

    if has_qr and sys.stdout.isatty():
        try:
            subprocess.run(["qrencode", "-t", "ANSIUTF8", "-m", "1", line], check=False)
        except FileNotFoundError:
            pass

    print(f"Wrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
