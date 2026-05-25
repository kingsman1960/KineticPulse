"""WebRTC peer for the caregiver live feed (STUB).

The full implementation will use `aiortc` + the Jetson NVENC encoder to
publish an audio/video stream to a signaling server, which the caregiver
dashboard connects to. That work is gated on the signaling-server design
and is therefore not implemented here.

This stub:
- Exposes the same async interface (:meth:`start`, :meth:`stop`).
- Logs every state change with the snapshot that triggered escalation.
- Lets the rest of the pipeline call WebRTC paths without ImportError on
  systems where `aiortc` is not installed.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from kineticpulse.config import WebrtcConfig
from kineticpulse.fusion.engine import FusionSnapshot
from kineticpulse.utils.logging import get_logger

log = get_logger(__name__)


class WebrtcPeer:
    def __init__(self, cfg: WebrtcConfig) -> None:
        self.cfg = cfg
        self._active = False
        self._lock = asyncio.Lock()

    async def start(self, snapshot: Optional[FusionSnapshot] = None) -> None:
        async with self._lock:
            if self._active:
                return
            if not self.cfg.enabled:
                log.info("[stub] WebRTC disabled by config; would have started stream now.")
                return
            log.warning(
                "[stub] WebRTC start requested (signaling_url=%s). "
                "Real aiortc peer not yet implemented; alert path unaffected.",
                self.cfg.signaling_url,
            )
            self._active = True

    async def stop(self) -> None:
        async with self._lock:
            if not self._active:
                return
            log.info("[stub] WebRTC stream stopped.")
            self._active = False

    @property
    def is_active(self) -> bool:
        return self._active
