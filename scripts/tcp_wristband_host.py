#!/usr/bin/env python3
"""Laptop TCP host for KineticPulse wristband bring-up.

Binds the same API as production Jetson telemetry:
  kineticpulse.sensors.tcp.TcpSensorServer  (default 0.0.0.0:5555)

ESP32 firmware (`src/main.cpp`) connects as a Wi-Fi TCP client and sends
NDJSON lines (`hello` / `hr` / `accel` / ...). See docs/TCP_CONTRACT.md.

Usage (same WLAN / hotspot as the ESP32 — not eduroam enterprise):

  python scripts/tcp_wristband_host.py
  python scripts/tcp_wristband_host.py --host 0.0.0.0 --port 5555
"""

from __future__ import annotations

import argparse
import asyncio
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kineticpulse.config import WristbandConfig
from kineticpulse.sensors.parser import AccelSample, HrSample, PulseLost
from kineticpulse.sensors.tcp import TcpSensorServer
from kineticpulse.utils.logging import configure_logging, get_logger

log = get_logger("tcp_host")


def _lan_ips() -> list[str]:
    ips: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    # Fallback: UDP trick for the primary outbound interface.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip not in ips:
            ips.insert(0, ip)
    except OSError:
        pass
    return ips


async def _printer(queue: asyncio.Queue) -> None:
    while True:
        ev = await queue.get()
        if isinstance(ev, HrSample):
            print(f"HR   bpm={ev.bpm}  ts={ev.timestamp_ms}", flush=True)
        elif isinstance(ev, AccelSample):
            print(
                f"ACC  ax={ev.ax:.3f} ay={ev.ay:.3f} az={ev.az:.3f}  "
                f"|g|={ev.magnitude_g:.3f}  ts={ev.timestamp_ms}",
                flush=True,
            )
        elif isinstance(ev, PulseLost):
            print(f"PULSE_LOST duration_s={ev.duration_s}  ts={ev.timestamp_ms}", flush=True)
        else:
            print(f"EVENT {ev!r}", flush=True)


async def main_async(host: str, port: int) -> int:
    configure_logging(level="INFO")
    cfg = WristbandConfig(
        transport="tcp",
        tcp_host=host,
        tcp_port=port,
        has_accelerometer=True,
        has_ppg_raw=False,  # firmware sends pre-computed hr lines
        tcp_idle_timeout_s=30.0,
    )
    queue: asyncio.Queue = asyncio.Queue(maxsize=512)
    server = TcpSensorServer(cfg, queue)

    ips = _lan_ips()
    print("=" * 60, flush=True)
    print("KineticPulse wristband TCP host (laptop)", flush=True)
    print(f"  Listening: {host}:{port}", flush=True)
    print("  Put this IP into src/wifi_secrets.h as SERVER_IP:", flush=True)
    for ip in ips or ["(unknown — check ipconfig)"]:
        print(f"    #define SERVER_IP \"{ip}\"", flush=True)
    print("  ESP32 and laptop must share a WPA2-PSK Wi-Fi", flush=True)
    print("  (phone hotspot). Campus eduroam usually will NOT work.", flush=True)
    print("=" * 60, flush=True)

    server_task = asyncio.create_task(server.run(), name="tcp-server")
    printer_task = asyncio.create_task(_printer(queue), name="printer")
    try:
        await server_task
    except asyncio.CancelledError:
        pass
    finally:
        server.stop()
        printer_task.cancel()
        try:
            await printer_task
        except asyncio.CancelledError:
            pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    parser.add_argument("--port", type=int, default=5555, help="TCP port")
    args = parser.parse_args()
    try:
        return asyncio.run(main_async(args.host, args.port))
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
