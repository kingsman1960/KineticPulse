"""TCP/Wi-Fi telemetry server for the KineticPulse wristband.

The hardware team pivoted away from BLE because peripheral
disconnections were too frequent on the wristband; the wristband is now
an ESP32 on the local Wi-Fi that opens a TCP connection to the Jetson
and pushes newline-delimited JSON.

This module implements the **Jetson side**:

* :class:`TcpSensorServer` runs an ``asyncio.start_server`` on
  ``cfg.tcp_host:cfg.tcp_port`` and handles one connection at a time
  (the wristband is single-tenant - if a second device connects the
  current one is closed). For each line of JSON it produces the same
  :class:`~kineticpulse.sensors.parser.SensorEvent` types the rest of
  the pipeline already consumes, so nothing downstream of the events
  queue needs to change.

Wire format (UTF-8, newline-delimited JSON, one event per line):

* Heart rate (computed BPM)::

    {"type":"hr","bpm":72,"ts":1758291234567}

* Accelerometer (3-axis, in g)::

    {"type":"accel","ax":0.10,"ay":0.02,"az":0.99,"ts":1758291234567}

* Raw PPG burst (MAX30102 IR + Red, ``len(ir) == len(red)``)::

    {"type":"ppg","ir":[1234,1235,...],"red":[1100,1101,...],"ts":1758291234567}

* Loss-of-pulse synthesised event::

    {"type":"pulse_lost","duration_s":3.0,"ts":1758291235000}

* Optional handshake on connect (logged, otherwise ignored)::

    {"type":"hello","device":"esp32-kp-001","fw":"0.1.0","caps":["hr","accel","ppg"]}

The ``ts`` field is informational only - the server timestamps every
event with the Jetson-side wall clock when it is consumed, mirroring
the BLE client's behaviour so fusion-engine timing is identical
regardless of transport.

Reconnection is the firmware's responsibility (TCP is a stream, not a
connectionless protocol); the server simply keeps listening.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from kineticpulse.config import WristbandConfig
from kineticpulse.sensors.parser import (
    AccelSample,
    HrSample,
    PulseLost,
    SensorEvent,
)
from kineticpulse.sensors.ppg import PpgProcessor, PpgSample
from kineticpulse.utils.logging import get_logger
from kineticpulse.utils.timing import now_ms

log = get_logger(__name__)


# -- helpers ---------------------------------------------------------------- #


def _parse_event(
    obj: Dict[str, Any],
    *,
    timestamp_ms: int,
    ppg_processor: Optional[PpgProcessor],
) -> List[SensorEvent]:
    """Translate one decoded JSON object into zero or more SensorEvents.

    A raw PPG burst yields zero or one :class:`HrSample` (the processor
    integrates samples and only emits a BPM about once per second), every
    other type yields exactly one event. Returns ``[]`` for handshake /
    unknown types so the caller just keeps reading.
    """
    et = obj.get("type")
    if et == "hr":
        try:
            bpm = int(obj["bpm"])
        except (KeyError, TypeError, ValueError):
            return []
        return [HrSample(bpm=bpm, timestamp_ms=timestamp_ms)]

    if et == "accel":
        try:
            ax = float(obj["ax"])
            ay = float(obj["ay"])
            az = float(obj["az"])
        except (KeyError, TypeError, ValueError):
            return []
        return [AccelSample(ax=ax, ay=ay, az=az, timestamp_ms=timestamp_ms)]

    if et == "pulse_lost":
        try:
            duration_s = float(obj.get("duration_s", 0.0))
        except (TypeError, ValueError):
            duration_s = 0.0
        return [PulseLost(duration_s=duration_s, timestamp_ms=timestamp_ms)]

    if et == "ppg":
        if ppg_processor is None:
            # Wristband sent raw PPG but the runtime is configured for
            # pre-computed HR; ignore rather than crash.
            return []
        ir = obj.get("ir") or []
        red = obj.get("red") or []
        if not isinstance(ir, list) or not isinstance(red, list):
            return []
        n = min(len(ir), len(red))
        if n == 0:
            return []
        # Stamp each sample with a timestamp such that the *last* sample
        # lands on `timestamp_ms`, mirroring parse_ppg_packet().
        period_ms = 1000.0 / max(1, ppg_processor.fs)
        out: List[SensorEvent] = []
        for i in range(n):
            try:
                sample = PpgSample(
                    ir=int(ir[i]),
                    red=int(red[i]),
                    timestamp_ms=int(timestamp_ms - (n - 1 - i) * period_ms),
                )
            except (TypeError, ValueError):
                continue
            hr = ppg_processor.push(sample)
            if hr is not None:
                out.append(hr)
        return out

    if et == "hello":
        log.info(
            "TCP: wristband hello device=%r fw=%r caps=%s",
            obj.get("device"), obj.get("fw"), obj.get("caps"),
        )
        return []

    # Unknown type - log once at debug and move on.
    log.debug("TCP: ignoring unknown event type %r", et)
    return []


# -- server ----------------------------------------------------------------- #


class TcpSensorServer:
    """Single-tenant TCP server for wristband telemetry."""

    def __init__(
        self,
        cfg: WristbandConfig,
        events: "asyncio.Queue[SensorEvent]",
    ) -> None:
        self.cfg = cfg
        self.events = events
        self._stop = asyncio.Event()
        self._server: Optional[asyncio.AbstractServer] = None
        self._active_writer: Optional[asyncio.StreamWriter] = None
        self._ppg_processor: Optional[PpgProcessor] = None
        if cfg.has_ppg_raw:
            self._ppg_processor = PpgProcessor(sample_rate_hz=cfg.ppg_sample_rate_hz)

    async def run(self) -> None:
        """Open the listening socket and serve until :meth:`stop` is called."""
        log.info(
            "TCP: capability flags has_accelerometer=%s has_ppg_raw=%s",
            self.cfg.has_accelerometer, self.cfg.has_ppg_raw,
        )
        self._server = await asyncio.start_server(
            self._handle_client,
            host=self.cfg.tcp_host,
            port=self.cfg.tcp_port,
        )
        sock_repr = ", ".join(str(s.getsockname()) for s in self._server.sockets or [])
        log.info("TCP: listening on %s (transport=tcp)", sock_repr)
        async with self._server:
            try:
                await self._stop.wait()
            finally:
                self._server.close()
                try:
                    await self._server.wait_closed()
                except Exception:
                    pass
                log.info("TCP: server closed.")

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        peer = writer.get_extra_info("peername")
        log.info("TCP: wristband connected from %s", peer)

        # Single-tenant: kick the previous client off so a freshly-restarted
        # ESP32 can reclaim the slot without waiting for TCP keepalive.
        if self._active_writer is not None and not self._active_writer.is_closing():
            log.warning("TCP: replacing previous wristband connection.")
            try:
                self._active_writer.close()
            except Exception:
                pass
        self._active_writer = writer
        if self._ppg_processor is not None:
            self._ppg_processor.reset()

        idle_timeout = self.cfg.tcp_idle_timeout_s
        line_cap = max(1024, self.cfg.tcp_max_line_bytes)
        try:
            while not self._stop.is_set():
                try:
                    raw = await asyncio.wait_for(
                        reader.readuntil(b"\n"),
                        timeout=idle_timeout,
                    )
                except asyncio.IncompleteReadError:
                    log.info("TCP: peer %s closed the connection.", peer)
                    return
                except asyncio.LimitOverrunError:
                    log.warning("TCP: line longer than buffer from %s; dropping connection.", peer)
                    return
                except asyncio.TimeoutError:
                    log.warning(
                        "TCP: no data from %s in %.1fs; closing for reconnect.",
                        peer, idle_timeout,
                    )
                    return

                if not raw:
                    return
                if len(raw) > line_cap:
                    log.warning("TCP: oversize line (%d bytes) from %s; ignoring.", len(raw), peer)
                    continue

                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    log.warning("TCP: bad JSON from %s: %s", peer, exc)
                    continue
                if not isinstance(obj, dict):
                    continue

                ts = now_ms()
                for ev in _parse_event(obj, timestamp_ms=ts, ppg_processor=self._ppg_processor):
                    self._submit(ev)
        finally:
            try:
                writer.close()
            except Exception:
                pass
            if self._active_writer is writer:
                self._active_writer = None
            log.info("TCP: connection from %s closed.", peer)

    def _submit(self, ev: SensorEvent) -> None:
        try:
            self.events.put_nowait(ev)
        except asyncio.QueueFull:
            try:
                _ = self.events.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self.events.put_nowait(ev)

    def stop(self) -> None:
        self._stop.set()
        # Best-effort: hang up on the current client too so readuntil() unblocks.
        if self._active_writer is not None and not self._active_writer.is_closing():
            try:
                self._active_writer.close()
            except Exception:
                pass
