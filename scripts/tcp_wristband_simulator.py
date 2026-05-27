#!/usr/bin/env python3
"""TCP wristband simulator for KineticPulse development.

Connects to the existing ``TcpSensorServer`` and sends newline-delimited
UTF-8 JSON events that match the README wristband schema. This is a small
developer tool for exercising the production TCP ingest path without ESP32
firmware.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import socket
import sys
import time
from typing import Any, Dict, Iterable, Iterator

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5555
DEFAULT_DEVICE = "esp32-kp-001"
DEFAULT_FW = "0.1.0"

ScenarioEvent = Dict[str, Any]


def monotonic_ts_ms() -> int:
    """Timestamp compatible with the README's informational ``ts`` field."""
    return int(time.monotonic() * 1000)


def hello_event(device: str = DEFAULT_DEVICE, fw: str = DEFAULT_FW) -> ScenarioEvent:
    return {
        "type": "hello",
        "device": device,
        "fw": fw,
        "caps": ["hr", "accel", "ppg"],
    }


def hr_event(bpm: int, ts: int) -> ScenarioEvent:
    return {"type": "hr", "bpm": int(bpm), "ts": ts}


def accel_event(ax: float, ay: float, az: float, ts: int) -> ScenarioEvent:
    return {
        "type": "accel",
        "ax": round(float(ax), 3),
        "ay": round(float(ay), 3),
        "az": round(float(az), 3),
        "ts": ts,
    }


def ppg_event(base_ir: int, base_red: int, ts: int, n: int = 16) -> ScenarioEvent:
    return {
        "type": "ppg",
        "ir": [base_ir + i for i in range(n)],
        "red": [base_red + i for i in range(n)],
        "ts": ts,
    }


def pulse_lost_event(duration_s: float, ts: int) -> ScenarioEvent:
    return {"type": "pulse_lost", "duration_s": float(duration_s), "ts": ts}


def iter_scenario_events(
    scenario: str,
    *,
    count: int,
    interval_s: float,
    include_ppg: bool,
) -> Iterator[ScenarioEvent]:
    """Yield README-compatible events for one simulator scenario.

    ``ts`` is generated at yield time because the server treats it as
    informational and stamps received events with Jetson-side time.
    """
    if count <= 0:
        return

    scenario = scenario.lower()
    if scenario == "resting":
        for i in range(count):
            ts = monotonic_ts_ms()
            yield hr_event(72 + (i % 3), ts)
            yield accel_event(0.02 * math.sin(i), 0.01 * math.cos(i), 0.99, ts)
            if include_ppg and i % 5 == 0:
                yield ppg_event(12_000 + i, 11_000 + i, ts)
            time.sleep(interval_s)
        return

    if scenario == "standard_fall":
        fall_idx = max(1, count // 3)
        for i in range(count):
            ts = monotonic_ts_ms()
            if i < fall_idx:
                bpm = 72 + (i % 2)
                accel = accel_event(0.0, 0.0, 1.0, ts)
            elif i == fall_idx:
                bpm = 108
                accel = accel_event(4.1, 0.4, 3.8, ts)
            else:
                bpm = min(124, 108 + (i - fall_idx) * 3)
                accel = accel_event(0.03 * math.sin(i), 0.02 * math.cos(i), 1.0, ts)
            yield hr_event(bpm, ts)
            yield accel
            if include_ppg and i % 5 == 0:
                yield ppg_event(12_300 + i, 11_300 + i, ts)
            time.sleep(interval_s)
        return

    if scenario == "pulse_lost":
        warmup = max(1, count // 3)
        for i in range(count):
            ts = monotonic_ts_ms()
            if i < warmup:
                yield hr_event(70 + (i % 4), ts)
                yield accel_event(0.0, 0.0, 1.0, ts)
            else:
                yield pulse_lost_event(3.0, ts)
                yield accel_event(0.02, 0.01, 1.0, ts)
            if include_ppg and i == 0:
                yield ppg_event(12_100, 11_100, ts)
            time.sleep(interval_s)
        return

    raise ValueError(f"Unknown scenario: {scenario}")


def encode_event(event: ScenarioEvent) -> bytes:
    return (json.dumps(event, separators=(",", ":")) + "\n").encode("utf-8")


def send_events(host: str, port: int, events: Iterable[ScenarioEvent], *, dry_run: bool) -> None:
    if dry_run:
        for event in events:
            print(f"SEND {json.dumps(event, ensure_ascii=False)}")
        return

    with socket.create_connection((host, port), timeout=5.0) as sock:
        for event in events:
            line = json.dumps(event, ensure_ascii=False)
            print(f"SEND {line}")
            sock.sendall(encode_event(event))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Send simulated ESP32 wristband TCP telemetry to KineticPulse.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--host", default=DEFAULT_HOST, help="TcpSensorServer host.")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help="TcpSensorServer port.")
    p.add_argument(
        "--scenario",
        choices=("resting", "standard_fall", "pulse_lost"),
        default="resting",
        help="Telemetry scenario to send.",
    )
    p.add_argument("--count", type=int, default=30, help="Number of scenario ticks.")
    p.add_argument("--interval-s", type=float, default=0.2, help="Delay between ticks.")
    p.add_argument("--no-ppg", action="store_true", help="Do not include sample PPG bursts.")
    p.add_argument("--device", default=DEFAULT_DEVICE, help="Device name in the hello event.")
    p.add_argument("--fw", default=DEFAULT_FW, help="Firmware version in the hello event.")
    p.add_argument("--dry-run", action="store_true", help="Print events without opening a socket.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    print(
        "KineticPulse TCP wristband simulator "
        f"scenario={args.scenario} target={args.host}:{args.port}"
    )
    events = itertools.chain(
        [hello_event(args.device, args.fw)],
        iter_scenario_events(
            args.scenario,
            count=args.count,
            interval_s=args.interval_s,
            include_ppg=not args.no_ppg,
        ),
    )
    try:
        send_events(args.host, args.port, events, dry_run=args.dry_run)
    except OSError as exc:
        print(f"[error] could not connect/send to {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
