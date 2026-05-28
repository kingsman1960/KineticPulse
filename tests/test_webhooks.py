"""Behavior tests for the async webhook dispatcher.

The dispatcher is part of the emergency path, so these tests keep all HTTP
I/O in memory while still exercising the real async dispatch logic:
enabled-hook filtering, payload shape, header forwarding, parallel fan-out,
failure isolation, lazy client creation, and shutdown cleanup.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from kineticpulse.alerts.payload import AlertPayload
from kineticpulse.alerts.webhooks import WebhookDispatcher
from kineticpulse.config import WebhookConfig


@dataclass
class FakeResponse:
    status_code: int = 200


class RecordingClient:
    def __init__(
        self,
        *,
        outcomes_by_url: Optional[Dict[str, object]] = None,
        close_error: Optional[Exception] = None,
    ) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.outcomes_by_url = outcomes_by_url or {}
        self.close_error = close_error
        self.close_count = 0

    async def post(
        self,
        url: str,
        *,
        headers: Dict[str, str],
        json: Dict[str, Any],
    ) -> FakeResponse:
        self.calls.append({"url": url, "headers": headers, "json": json})
        outcome = self.outcomes_by_url.get(url, FakeResponse(200))
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, FakeResponse)
        return outcome

    async def aclose(self) -> None:
        self.close_count += 1
        if self.close_error is not None:
            raise self.close_error


class ParallelProbeClient:
    def __init__(self, expected_posts: int) -> None:
        self.expected_posts = expected_posts
        self.calls: List[str] = []
        self.all_posts_started = asyncio.Event()

    async def post(
        self,
        url: str,
        *,
        headers: Dict[str, str],
        json: Dict[str, Any],
    ) -> FakeResponse:
        self.calls.append(url)
        if len(self.calls) == self.expected_posts:
            self.all_posts_started.set()
        await asyncio.wait_for(self.all_posts_started.wait(), timeout=0.5)
        return FakeResponse(200)


def _payload() -> AlertPayload:
    return AlertPayload(
        subject_id="subject-001",
        location="Apartment 4B",
        nature="Unverified Fall",
        scenario="standard_fall",
        severity="elevated",
        tier="tier_1_verify",
        reason="cv_downward_motion_and_hr_spike",
        vitals={
            "heart_rate_bpm": 112,
            "hr_signature": "panic_spike",
            "accel_magnitude_g": 3.4,
            "accel_signature": "impact_then_still",
        },
        detector={
            "class": "fallen",
            "confidence": 0.91,
            "pose_signature": "fallen",
        },
        voice={"transcript": "help", "verdict": "distress"},
        timestamp_ms=1_234_567,
    )


def _hook(
    name: str,
    url: str,
    *,
    enabled: bool = True,
    headers: Optional[Dict[str, str]] = None,
) -> WebhookConfig:
    return WebhookConfig(
        name=name,
        url=url,
        headers=headers or {},
        enabled=enabled,
    )


def test_dispatch_without_enabled_webhooks_does_not_send_or_open_client(
    caplog,
    monkeypatch,
) -> None:
    async def _run() -> None:
        payload = _payload()
        dispatcher = WebhookDispatcher([
            _hook("disabled", "https://example.invalid/disabled", enabled=False),
        ])

        async def fail_if_client_is_requested():
            raise AssertionError("disabled webhooks must not create an HTTP client")

        monkeypatch.setattr(dispatcher, "_get_client", fail_if_client_is_requested)

        with caplog.at_level(logging.INFO, logger="kineticpulse.alerts.webhooks"):
            await dispatcher.dispatch(payload)

        assert "No enabled webhooks" in caplog.text
        assert payload.subject_id in caplog.text

    asyncio.run(_run())


def test_dispatch_posts_payload_and_headers_to_enabled_webhooks_only() -> None:
    async def _run() -> None:
        payload = _payload()
        client = RecordingClient()
        dispatcher = WebhookDispatcher([
            _hook("slack", "https://hooks.example/slack",
                  headers={"Authorization": "Bearer slack-token"}),
            _hook("disabled", "https://hooks.example/disabled", enabled=False),
            _hook("sms", "https://hooks.example/sms",
                  headers={"X-Route": "urgent"}),
        ])
        dispatcher._client = client

        await dispatcher.dispatch(payload)

        assert [call["url"] for call in client.calls] == [
            "https://hooks.example/slack",
            "https://hooks.example/sms",
        ]
        assert client.calls[0]["headers"] == {"Authorization": "Bearer slack-token"}
        assert client.calls[1]["headers"] == {"X-Route": "urgent"}
        assert all(call["json"] == payload.as_json() for call in client.calls)

    asyncio.run(_run())


def test_dispatch_fans_out_to_enabled_webhooks_in_parallel() -> None:
    async def _run() -> None:
        client = ParallelProbeClient(expected_posts=2)
        dispatcher = WebhookDispatcher([
            _hook("primary", "https://hooks.example/primary"),
            _hook("backup", "https://hooks.example/backup"),
        ])
        dispatcher._client = client

        await asyncio.wait_for(dispatcher.dispatch(_payload()), timeout=1.0)

        assert set(client.calls) == {
            "https://hooks.example/primary",
            "https://hooks.example/backup",
        }

    asyncio.run(_run())


def test_dispatch_isolates_one_webhook_failure_and_keeps_other_sends(caplog) -> None:
    async def _run() -> None:
        client = RecordingClient(outcomes_by_url={
            "https://hooks.example/broken": RuntimeError("connection refused"),
            "https://hooks.example/working": FakeResponse(202),
        })
        dispatcher = WebhookDispatcher([
            _hook("broken", "https://hooks.example/broken"),
            _hook("working", "https://hooks.example/working"),
        ])
        dispatcher._client = client

        with caplog.at_level(logging.WARNING, logger="kineticpulse.alerts.webhooks"):
            await dispatcher.dispatch(_payload())

        assert {call["url"] for call in client.calls} == {
            "https://hooks.example/broken",
            "https://hooks.example/working",
        }
        assert "Webhook broken failed: connection refused" in caplog.text

    asyncio.run(_run())


def test_dispatch_lazily_creates_reuses_and_closes_http_client(monkeypatch) -> None:
    async def _run() -> None:
        created_clients: List[RecordingClient] = []

        class FakeAsyncClient(RecordingClient):
            def __init__(self, *, timeout: float, http2: bool) -> None:
                super().__init__()
                self.timeout = timeout
                self.http2 = http2
                created_clients.append(self)

        monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(AsyncClient=FakeAsyncClient))
        dispatcher = WebhookDispatcher([
            _hook("slack", "https://hooks.example/slack"),
        ], timeout_s=1.25)

        await dispatcher.dispatch(_payload())
        await dispatcher.dispatch(_payload())

        assert len(created_clients) == 1
        assert created_clients[0].timeout == 1.25
        assert created_clients[0].http2 is True
        assert len(created_clients[0].calls) == 2

        await dispatcher.aclose()

        assert created_clients[0].close_count == 1

        await dispatcher.dispatch(_payload())

        assert len(created_clients) == 2
        assert len(created_clients[1].calls) == 1

    asyncio.run(_run())


def test_aclose_suppresses_close_errors_and_clears_client() -> None:
    async def _run() -> None:
        client = RecordingClient(close_error=RuntimeError("close failed"))
        dispatcher = WebhookDispatcher([
            _hook("slack", "https://hooks.example/slack"),
        ])
        dispatcher._client = client

        await dispatcher.aclose()

        assert client.close_count == 1
        assert dispatcher._client is None

    asyncio.run(_run())
