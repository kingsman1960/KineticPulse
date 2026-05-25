"""Async webhook dispatcher.

Sends the alert payload to every enabled webhook in parallel with a short
timeout. Failures are logged but never raised, so one slow / misconfigured
endpoint cannot block an emergency notification path.
"""

from __future__ import annotations

import asyncio
from typing import Iterable, List, Optional

from kineticpulse.alerts.payload import AlertPayload
from kineticpulse.config import WebhookConfig
from kineticpulse.utils.logging import get_logger

log = get_logger(__name__)


class WebhookDispatcher:
    def __init__(self, webhooks: Iterable[WebhookConfig], timeout_s: float = 5.0) -> None:
        self.webhooks: List[WebhookConfig] = [w for w in webhooks if w.enabled]
        self.timeout_s = timeout_s
        self._client = None

    async def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import httpx
        except ImportError as exc:
            raise ImportError(
                "httpx is required. Install with `pip install -r requirements.txt`."
            ) from exc
        self._client = httpx.AsyncClient(timeout=self.timeout_s, http2=True)
        return self._client

    async def dispatch(self, payload: AlertPayload) -> None:
        if not self.webhooks:
            log.info("No enabled webhooks; payload would be: %s", payload.as_json())
            return
        client = await self._get_client()
        coros = [self._send_one(client, w, payload) for w in self.webhooks]
        await asyncio.gather(*coros, return_exceptions=True)

    async def _send_one(self, client, wh: WebhookConfig, payload: AlertPayload) -> None:
        try:
            resp = await client.post(wh.url, headers=wh.headers, json=payload.as_json())
            log.info("Webhook %s -> %s (%d)", wh.name, wh.url, resp.status_code)
        except Exception as exc:
            log.warning("Webhook %s failed: %s", wh.name, exc)

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None
