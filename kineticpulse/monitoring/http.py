"""Stdlib HTTP publisher for the caregiver dashboard monitoring contract.

Serves ``GET /monitoring`` as the ``MonitoringWirePayload`` envelope expected by
``dashboard/lib/monitoring/backendMonitoringAdapter.ts``. Continuous vitals
come from :attr:`FusionEngine.latest`; emergencies still go through webhooks /
WebRTC separately.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable, Dict, List, Optional

from kineticpulse.config import AlertsConfig
from kineticpulse.fusion.engine import FusionSnapshot
from kineticpulse.runtime_status import CaregiverRuntimeStatus
from kineticpulse.utils.logging import get_logger

log = get_logger(__name__)

_VISION = frozenset({"fallen", "falling", "stand", "sitting"})


def _sensor_connection(sensors: Any) -> str:
    connected = getattr(sensors, "connected", None)
    if connected is True:
        return "connected"
    if connected is False:
        return "disconnected"
    return "degraded"


def _vision_class(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    key = value.lower()
    return key if key in _VISION else None


def build_monitoring_payload(
    *,
    alerts: AlertsConfig,
    snapshot: Optional[FusionSnapshot],
    sensors: Any = None,
    voice_status: str = "not_required",
    alert_dispatch_status: str = "idle",
    events: Optional[List[Dict[str, Any]]] = None,
    published_at_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """Build the JSON envelope consumed by the Next.js real-mode adapter."""
    wire_timestamp_ms = (
        published_at_ms
        if published_at_ms is not None
        else int(time.time() * 1000)
    )
    sensor_conn = _sensor_connection(sensors)
    event_list = list(events or [])
    if snapshot is None:
        return {
            "subject_id": alerts.subject_id,
            "location": alerts.location,
            "system": {"connection": "connected"},
            "sensor": {"connection": sensor_conn},
            "snapshot": {
                "decision": {
                    "tier": "none",
                    "scenario": "monitoring",
                    "reason": "Fusion engine warming up.",
                },
                "pose": "unknown",
                "accel": "unknown",
                "hr": "unknown",
                "latest_hr_bpm": None,
                "latest_accel_g": None,
                "detector_class": None,
                "detector_conf": None,
                "action_class": None,
                "action_conf": None,
                "timestamp_ms": wire_timestamp_ms,
            },
            "voice": {"status": voice_status},
            "alert_dispatch": {"status": alert_dispatch_status},
            "events": event_list,
        }

    return {
        "subject_id": alerts.subject_id,
        "location": alerts.location,
        "system": {"connection": "connected"},
        "sensor": {"connection": sensor_conn},
        "snapshot": {
            "decision": {
                "tier": snapshot.decision.tier.value,
                "scenario": snapshot.decision.scenario,
                "reason": snapshot.decision.reason,
            },
            "pose": snapshot.pose.value,
            "accel": snapshot.accel.value,
            "hr": snapshot.hr.value,
            "latest_hr_bpm": snapshot.latest_hr_bpm,
            "latest_accel_g": snapshot.latest_accel_g,
            "detector_class": _vision_class(snapshot.detector_class),
            "detector_conf": snapshot.detector_conf,
            "action_class": snapshot.action_class,
            "action_conf": snapshot.action_conf,
            # Fusion timestamps are monotonic for sensor-window calculations;
            # the dashboard contract requires Unix epoch milliseconds.
            "timestamp_ms": wire_timestamp_ms,
        },
        "voice": {"status": voice_status},
        "alert_dispatch": {"status": alert_dispatch_status},
        "events": event_list,
    }


class MonitoringPublisher:
    """Tiny asyncio HTTP server: ``GET /monitoring`` (+ ``/healthz``)."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        alerts: AlertsConfig,
        latest_snapshot: Callable[[], Optional[FusionSnapshot]],
        sensors: Any = None,
        runtime_status: Optional[CaregiverRuntimeStatus] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.alerts = alerts
        self.latest_snapshot = latest_snapshot
        self.sensors = sensors
        self.runtime_status = runtime_status or CaregiverRuntimeStatus()
        self._server: Optional[asyncio.AbstractServer] = None
        self._stop = asyncio.Event()

    async def run(self) -> None:
        self._server = await asyncio.start_server(
            self._handle, host=self.host, port=self.port
        )
        socks = ", ".join(str(s.getsockname()) for s in self._server.sockets or [])
        log.info("Monitoring HTTP listening on %s (GET /monitoring)", socks)
        async with self._server:
            try:
                await self._stop.wait()
            finally:
                self._server.close()
                try:
                    await self._server.wait_closed()
                except Exception:
                    pass

    def stop(self) -> None:
        self._stop.set()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5.0)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            writer.close()
            return

        request_line = raw.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
        parts = request_line.split()
        method = parts[0] if parts else ""
        target = parts[1] if len(parts) > 1 else "/"
        path = target.split("?", 1)[0]

        if method == "OPTIONS":
            await self._respond(writer, 204, b"", content_type=None)
            return

        if method != "GET":
            await self._respond(writer, 405, b'{"ok":false,"error":"method_not_allowed"}')
            return

        if path in ("/healthz", "/"):
            await self._respond(writer, 200, b'{"ok":true}')
            return

        if path != "/monitoring":
            await self._respond(writer, 404, b'{"ok":false,"error":"not_found"}')
            return

        status = self.runtime_status
        body = json.dumps(
            build_monitoring_payload(
                alerts=self.alerts,
                snapshot=self.latest_snapshot(),
                sensors=self.sensors,
                voice_status=status.voice_status,
                alert_dispatch_status=status.alert_dispatch_status,
                events=status.events_payload(),
            ),
            separators=(",", ":"),
        ).encode("utf-8")
        await self._respond(writer, 200, body)

    async def _respond(
        self,
        writer: asyncio.StreamWriter,
        status: int,
        body: bytes,
        *,
        content_type: Optional[str] = "application/json",
    ) -> None:
        reason = {
            200: "OK",
            204: "No Content",
            404: "Not Found",
            405: "Method Not Allowed",
        }.get(status, "OK")
        headers = [
            f"HTTP/1.1 {status} {reason}",
            "Connection: close",
            "Cache-Control: no-store",
            f"Content-Length: {len(body)}",
        ]
        if content_type:
            headers.append(f"Content-Type: {content_type}")
        writer.write(("\r\n".join(headers) + "\r\n\r\n").encode("latin-1") + body)
        try:
            await writer.drain()
        except Exception:
            pass
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
