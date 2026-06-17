"""WebSocket signaling client for aiortc peers."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from kineticpulse.utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class SignalMessage:
    type: str
    payload: Dict[str, Any]


class SignalingClient:
    """Tiny JSON-over-WebSocket signaling client.

    Expected schema:
      {"type":"...", "payload":{...}}
    """

    def __init__(
        self,
        url: str,
        *,
        auth_token: Optional[str] = None,
        connect_timeout_s: float = 8.0,
    ) -> None:
        self.url = url
        self.auth_token = auth_token
        self.connect_timeout_s = float(connect_timeout_s)
        self._ws = None
        self._rx_q: "asyncio.Queue[SignalMessage]" = asyncio.Queue(maxsize=128)
        self._reader_task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        if self._ws is not None:
            return
        try:
            import websockets
        except ImportError as exc:
            raise ImportError(
                "websockets is required for signaling. Install via requirements.txt."
            ) from exc

        headers = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        connect_kwargs = {}
        if headers:
            # websockets<12 uses extra_headers; >=12 supports additional_headers.
            connect_kwargs["extra_headers"] = headers
        self._ws = await asyncio.wait_for(
            websockets.connect(self.url, **connect_kwargs),
            timeout=self.connect_timeout_s,
        )
        self._reader_task = asyncio.create_task(self._reader_loop(), name="webrtc-signal-rx")
        log.info("Signaling connected: %s", self.url)

    async def close(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except Exception:
                pass
            self._reader_task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def send(self, msg_type: str, payload: Dict[str, Any]) -> None:
        if self._ws is None:
            raise RuntimeError("Signaling socket is not connected.")
        raw = json.dumps({"type": msg_type, "payload": payload}, ensure_ascii=False)
        await self._ws.send(raw)

    async def recv(self, timeout_s: Optional[float] = None) -> SignalMessage:
        if timeout_s is None:
            return await self._rx_q.get()
        return await asyncio.wait_for(self._rx_q.get(), timeout=timeout_s)

    async def _reader_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    data = json.loads(raw)
                    msg = SignalMessage(
                        type=str(data.get("type", "")),
                        payload=dict(data.get("payload") or {}),
                    )
                except Exception:
                    log.warning("Invalid signaling frame: %r", raw)
                    continue
                try:
                    self._rx_q.put_nowait(msg)
                except asyncio.QueueFull:
                    _ = self._rx_q.get_nowait()
                    self._rx_q.put_nowait(msg)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.warning("Signaling reader stopped: %s", exc)

