"""WebRTC peer for caregiver live feed.

Design goals:
- Never block/kill emergency dispatch flow if WebRTC fails.
- Keep `start()` idempotent and safe for repeated escalation events.
- Support signaling over secure WebSocket with token auth.
- Gracefully degrade when aiortc native deps are unavailable.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Optional

from kineticpulse.config import CameraConfig, WebrtcConfig
from kineticpulse.fusion.engine import FusionSnapshot
from kineticpulse.utils.logging import get_logger
from kineticpulse.webrtc.signaling_client import SignalingClient
from kineticpulse.webrtc.tracks import CameraVideoTrack
from kineticpulse.webrtc.types import WebrtcSessionMeta

log = get_logger(__name__)


class WebrtcPeer:
    def __init__(
        self,
        cfg: WebrtcConfig,
        *,
        camera_cfg: Optional[CameraConfig] = None,
        subject_id: str = "subject-001",
        location: str = "Unknown",
    ) -> None:
        self.cfg = cfg
        self.camera_cfg = camera_cfg or CameraConfig()
        self.subject_id = subject_id
        self.location = location
        self._active = False
        self._lock = asyncio.Lock()
        self._pc = None
        self._signal: Optional[SignalingClient] = None
        self._camera_track = None
        self._session_id: Optional[str] = None
        self._signal_task: Optional[asyncio.Task] = None
        self._session_timer_task: Optional[asyncio.Task] = None

    async def start(
        self,
        snapshot: Optional[FusionSnapshot] = None,
        *,
        session_id: Optional[str] = None,
        session_meta: Optional[WebrtcSessionMeta] = None,
    ) -> None:
        async with self._lock:
            if self._active:
                return
            if not self.cfg.enabled:
                log.info("WebRTC disabled by config; skip start.")
                return
            if not self.cfg.signaling_url:
                log.warning("WebRTC enabled but signaling_url is empty; skip start.")
                return

            try:
                await self._start_internal(snapshot, session_id=session_id, session_meta=session_meta)
            except ImportError as exc:
                # Keep emergency path alive when aiortc stack is unavailable.
                log.warning("WebRTC dependencies missing (%s). Alert path continues.", exc)
            except Exception as exc:
                log.warning("WebRTC start failed: %s", exc)

    async def stop(self) -> None:
        async with self._lock:
            if not self._active:
                return
            await self._stop_internal()
            self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    async def _start_internal(
        self,
        snapshot: Optional[FusionSnapshot],
        *,
        session_id: Optional[str],
        session_meta: Optional[WebrtcSessionMeta],
    ) -> None:
        try:
            from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
        except ImportError:
            raise

        sid = session_id or f"{self.cfg.session_id_prefix}-{uuid.uuid4().hex[:12]}"
        self._session_id = sid
        self._signal = SignalingClient(
            self.cfg.signaling_url,
            auth_token=self.cfg.auth_token,
            connect_timeout_s=self.cfg.connect_timeout_s,
        )
        await self._signal.connect()

        ice_servers = []
        for s in self.cfg.ice_servers:
            ice_servers.append(RTCIceServer(**s.as_rtc_kwargs()))
        pc = RTCPeerConnection(configuration=RTCConfiguration(iceServers=ice_servers))
        self._pc = pc

        @pc.on("connectionstatechange")
        async def _on_connstate() -> None:
            log.info("WebRTC connection state: %s (session=%s)", pc.connectionState, sid)
            if pc.connectionState in ("failed", "closed", "disconnected"):
                await self.stop()

        @pc.on("icecandidate")
        async def _on_ice(candidate) -> None:
            if candidate is None or self._signal is None:
                return
            from aiortc.rtcicetransport import candidate_to_sdp
            await self._signal.send("ice-candidate", {
                "session_id": sid,
                "candidate": candidate_to_sdp(candidate),
                "sdpMid": candidate.sdpMid,
                "sdpMLineIndex": candidate.sdpMLineIndex,
            })

        self._camera_track = CameraVideoTrack(self.camera_cfg)
        pc.addTrack(self._camera_track)

        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)

        if session_meta is None:
            session_meta = self._snapshot_to_meta(sid, snapshot)
        await self._signal.send("create-session", {
            "session_id": sid,
            "meta": session_meta.as_dict(),
            "offer": {
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type,
            },
        })

        msg = await self._signal.recv(timeout_s=self.cfg.connect_timeout_s)
        if msg.type != "answer":
            raise RuntimeError(f"Expected answer, got {msg.type!r}")
        answer = msg.payload.get("answer") or {}
        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=answer["sdp"], type=answer["type"])
        )

        self._active = True
        self._signal_task = asyncio.create_task(self._signal_loop(), name="webrtc-signal-loop")
        if self.cfg.max_session_s > 0:
            self._session_timer_task = asyncio.create_task(
                self._auto_stop_after(self.cfg.max_session_s),
                name="webrtc-auto-stop",
            )
        log.warning("WebRTC session started: %s", sid)

    async def _stop_internal(self) -> None:
        sid = self._session_id
        if self._signal_task is not None:
            self._signal_task.cancel()
            try:
                await self._signal_task
            except Exception:
                pass
            self._signal_task = None
        if self._session_timer_task is not None:
            self._session_timer_task.cancel()
            try:
                await self._session_timer_task
            except Exception:
                pass
            self._session_timer_task = None
        if self._signal is not None and sid:
            try:
                await self._signal.send("close-session", {"session_id": sid})
            except Exception:
                pass
        if self._camera_track is not None:
            try:
                self._camera_track.stop()
            except Exception:
                pass
            self._camera_track = None
        if self._pc is not None:
            try:
                await self._pc.close()
            except Exception:
                pass
            self._pc = None
        if self._signal is not None:
            await self._signal.close()
            self._signal = None
        self._session_id = None
        log.info("WebRTC session stopped.")

    async def _signal_loop(self) -> None:
        if self._signal is None or self._pc is None:
            return
        try:
            while True:
                try:
                    msg = await self._signal.recv(timeout_s=30.0)
                except asyncio.TimeoutError:
                    continue
                if msg.type == "ice-candidate":
                    payload = msg.payload
                    candidate = payload.get("candidate")
                    if not candidate:
                        continue
                    try:
                        from aiortc.rtcicetransport import candidate_from_sdp
                        c = candidate_from_sdp(candidate)
                        c.sdpMid = payload.get("sdpMid")
                        c.sdpMLineIndex = payload.get("sdpMLineIndex")
                        await self._pc.addIceCandidate(c)
                    except Exception as exc:
                        log.warning("Failed to add remote ICE candidate: %s", exc)
                elif msg.type == "session-closed":
                    await self.stop()
                    return
        except asyncio.CancelledError:
            return
        except Exception as exc:
            log.warning("Signal loop stopped: %s", exc)

    async def _auto_stop_after(self, seconds: float) -> None:
        try:
            await asyncio.sleep(seconds)
            await self.stop()
        except asyncio.CancelledError:
            return

    def _snapshot_to_meta(self, session_id: str, snapshot: Optional[FusionSnapshot]) -> WebrtcSessionMeta:
        if snapshot is None:
            return WebrtcSessionMeta(
                session_id=session_id,
                timestamp_ms=0,
                tier="unknown",
                scenario="unknown",
                subject_id=self.subject_id,
                location=self.location,
                reason="no snapshot",
            )
        d = snapshot.decision
        return WebrtcSessionMeta(
            session_id=session_id,
            timestamp_ms=snapshot.timestamp_ms,
            tier=d.tier.value,
            scenario=d.scenario,
            subject_id=self.subject_id,
            location=self.location,
            reason=d.reason,
            detector_class=snapshot.detector_class,
            action_class=snapshot.action_class,
            action_confidence=snapshot.action_conf,
        )
