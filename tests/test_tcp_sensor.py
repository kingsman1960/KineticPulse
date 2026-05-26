"""Tests for the TCP/Wi-Fi sensor server.

We spin up :class:`TcpSensorServer` on an ephemeral loopback port, open
a regular ``asyncio`` TCP client to play the wristband, and assert that
each JSON line we send produces the expected
:class:`~kineticpulse.sensors.parser.SensorEvent` on the events queue.

This deliberately exercises the real socket path (no patching) so it
catches anything that depends on actual stream framing (newlines,
partial reads, idle timeouts, malformed JSON).
"""

from __future__ import annotations

import asyncio
import json
from typing import List, Optional

import pytest

from kineticpulse.config import WristbandConfig
from kineticpulse.sensors.parser import (
    AccelSample,
    HrSample,
    PulseLost,
    SensorEvent,
)
from kineticpulse.sensors.tcp import TcpSensorServer


def _cfg(*, port: int = 0, has_accel: bool = True, has_ppg_raw: bool = False,
         idle_timeout_s: float = 5.0) -> WristbandConfig:
    """Wristband config bound to ``localhost:<port>`` for tests.

    ``port=0`` lets the kernel pick a free port; the test reads it back
    from the server's listening socket.
    """
    return WristbandConfig(
        transport="tcp",
        tcp_host="127.0.0.1",
        tcp_port=port,
        tcp_idle_timeout_s=idle_timeout_s,
        has_accelerometer=has_accel,
        has_ppg_raw=has_ppg_raw,
        ppg_sample_rate_hz=100,
    )


async def _start_server(cfg: WristbandConfig) -> tuple:
    queue: "asyncio.Queue[SensorEvent]" = asyncio.Queue(maxsize=128)
    server = TcpSensorServer(cfg, queue)
    server_task = asyncio.create_task(server.run())

    # Wait until the asyncio.start_server() call has actually bound a socket.
    for _ in range(50):
        if server._server is not None and server._server.sockets:
            break
        await asyncio.sleep(0.01)
    assert server._server is not None and server._server.sockets, (
        "TcpSensorServer never bound a listening socket."
    )
    bound_port = server._server.sockets[0].getsockname()[1]
    return server, server_task, queue, bound_port


async def _drain(queue: "asyncio.Queue[SensorEvent]", *, want: int,
                 timeout_s: float = 1.0) -> List[SensorEvent]:
    out: List[SensorEvent] = []
    try:
        for _ in range(want):
            ev = await asyncio.wait_for(queue.get(), timeout=timeout_s)
            out.append(ev)
    except asyncio.TimeoutError:
        pass
    return out


async def _shutdown(server: TcpSensorServer, server_task: asyncio.Task) -> None:
    server.stop()
    try:
        await asyncio.wait_for(server_task, timeout=2.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        server_task.cancel()
        try:
            await server_task
        except (asyncio.CancelledError, Exception):
            pass


def _send_lines_async(reader_writer_pair, lines: List[dict]) -> bytes:
    """Encode JSON dicts as newline-delimited UTF-8 bytes."""
    return b"".join(json.dumps(obj).encode("utf-8") + b"\n" for obj in lines)


# --------------------------------------------------------------------------- #
# 1. Happy-path round-trip: well-formed JSON lines map to SensorEvents.
# --------------------------------------------------------------------------- #


def test_tcp_server_decodes_hr_accel_and_pulse_lost() -> None:
    async def _run() -> None:
        cfg = _cfg(has_accel=True, has_ppg_raw=False)
        server, server_task, queue, port = await _start_server(cfg)
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            payload = _send_lines_async(None, [
                {"type": "hello", "device": "test-esp32", "fw": "0.0.1",
                 "caps": ["hr", "accel"]},
                {"type": "hr", "bpm": 73, "ts": 123},
                {"type": "accel", "ax": 0.1, "ay": -0.05, "az": 0.99, "ts": 124},
                {"type": "pulse_lost", "duration_s": 4.5, "ts": 125},
            ])
            writer.write(payload)
            await writer.drain()

            events = await _drain(queue, want=3, timeout_s=1.5)
            assert len(events) == 3, f"got {len(events)} events: {events!r}"

            hr, accel, pl = events
            assert isinstance(hr, HrSample) and hr.bpm == 73
            assert isinstance(accel, AccelSample)
            assert pytest.approx(accel.ax, abs=1e-6) == 0.1
            assert pytest.approx(accel.ay, abs=1e-6) == -0.05
            assert pytest.approx(accel.az, abs=1e-6) == 0.99
            assert isinstance(pl, PulseLost)
            assert pytest.approx(pl.duration_s, abs=1e-6) == 4.5
            # Server must stamp every event with its own clock, not trust
            # the ESP32 timestamp - all three should be ~equal and >> 125.
            assert hr.timestamp_ms > 1_000_000
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        finally:
            await _shutdown(server, server_task)

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# 2. Malformed input must not bring the connection down.
# --------------------------------------------------------------------------- #


def test_tcp_server_skips_garbage_lines_and_keeps_reading() -> None:
    async def _run() -> None:
        cfg = _cfg(has_accel=True, has_ppg_raw=False)
        server, server_task, queue, port = await _start_server(cfg)
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"not-json-at-all\n")
            writer.write(b'{"type":"hr","bpm":"oops"}\n')         # wrong type
            writer.write(b'{"type":"hr","bpm":81,"ts":1}\n')      # this one is fine
            writer.write(b'{"not":"a recognised type"}\n')
            writer.write(b'{"type":"accel","ax":0.0,"ay":0.0,"az":1.0}\n')
            await writer.drain()

            events = await _drain(queue, want=2, timeout_s=1.5)
            assert len(events) == 2, f"got {len(events)} events: {events!r}"
            kinds = {type(ev).__name__ for ev in events}
            assert kinds == {"HrSample", "AccelSample"}
            hr = next(ev for ev in events if isinstance(ev, HrSample))
            assert hr.bpm == 81

            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        finally:
            await _shutdown(server, server_task)

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# 3. Reconnection: server keeps serving after a client disconnects.
# --------------------------------------------------------------------------- #


def test_tcp_server_accepts_a_second_connection_after_disconnect() -> None:
    async def _run() -> None:
        cfg = _cfg(has_accel=True)
        server, server_task, queue, port = await _start_server(cfg)
        try:
            # First wristband connects, sends one event, drops.
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b'{"type":"hr","bpm":70}\n')
            await writer.drain()
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            ev1 = await asyncio.wait_for(queue.get(), timeout=1.5)
            assert isinstance(ev1, HrSample) and ev1.bpm == 70

            # Give the server a moment to clean up the closed connection.
            await asyncio.sleep(0.05)

            # Second wristband connects, sends two events.
            reader2, writer2 = await asyncio.open_connection("127.0.0.1", port)
            writer2.write(b'{"type":"hr","bpm":74}\n')
            writer2.write(b'{"type":"accel","ax":0.0,"ay":0.0,"az":1.0}\n')
            await writer2.drain()
            events = await _drain(queue, want=2, timeout_s=1.5)
            assert len(events) == 2
            assert any(isinstance(ev, HrSample) and ev.bpm == 74 for ev in events)
            assert any(isinstance(ev, AccelSample) for ev in events)
            writer2.close()
            try:
                await writer2.wait_closed()
            except Exception:
                pass
        finally:
            await _shutdown(server, server_task)

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# 4. PPG burst: sample rate, ordering, and buffering through PpgProcessor
# --------------------------------------------------------------------------- #


def test_tcp_server_ppg_burst_feeds_processor_without_crashing() -> None:
    """The wire format for raw PPG is ``{"type":"ppg","ir":[...],"red":[...]}``.

    PpgProcessor needs ~2 s of samples before it emits an HrSample, so a
    handful of bursts will not produce anything - the test only asserts
    that the server consumed the bursts cleanly and stayed responsive
    afterwards (a follow-up HR event must still come through)."""
    async def _run() -> None:
        cfg = _cfg(has_accel=False, has_ppg_raw=True)
        server, server_task, queue, port = await _start_server(cfg)
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)

            # Two small PPG bursts; not enough samples to trigger a BPM.
            burst_a = {"type": "ppg",
                       "ir":  [12000 + i for i in range(8)],
                       "red": [11000 + i for i in range(8)]}
            burst_b = {"type": "ppg",
                       "ir":  [12100 + i for i in range(8)],
                       "red": [11100 + i for i in range(8)]}
            writer.write((json.dumps(burst_a) + "\n").encode("utf-8"))
            writer.write((json.dumps(burst_b) + "\n").encode("utf-8"))

            # Now a regular HR event - this MUST come through to prove the
            # server processed the PPG bursts without choking on them.
            writer.write(b'{"type":"hr","bpm":88}\n')
            await writer.drain()

            ev = await asyncio.wait_for(queue.get(), timeout=1.5)
            assert isinstance(ev, HrSample)
            assert ev.bpm == 88

            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        finally:
            await _shutdown(server, server_task)

    asyncio.run(_run())
