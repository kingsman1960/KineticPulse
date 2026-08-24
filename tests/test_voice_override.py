"""Tier-1 voice verification: the two branches that must not block.

Both cover ``_dispatch_worker`` directly rather than the whole orchestrator,
so a regression points at the verification logic instead of the pipeline.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import List, Optional

import pytest

from kineticpulse.alerts.payload import AlertPayload
from kineticpulse.alerts.webhooks import WebhookDispatcher
from kineticpulse.config import RuntimeConfig
from kineticpulse.fusion.engine import FusionSnapshot
from kineticpulse.fusion.rules import AccelSignature, HrSignature, PoseSignature
from kineticpulse.fusion.tiers import EmergencyTier, TierDecision
from kineticpulse.main import _dispatch_worker
from kineticpulse.runtime_status import CaregiverRuntimeStatus
from kineticpulse.utils.timing import now_ms


def _snapshot(tier: EmergencyTier, scenario: str, reason: str) -> FusionSnapshot:
    return FusionSnapshot(
        decision=TierDecision(tier=tier, scenario=scenario, reason=reason),
        pose=PoseSignature.PRONE,
        accel=AccelSignature.IMPACT_ONLY,
        hr=HrSignature.PULSE_LOST if tier.bypasses_voice else HrSignature.PANIC_SPIKE,
        latest_hr_bpm=None if tier.bypasses_voice else 115,
        latest_accel_g=4.0,
        detector_class="fallen",
        detector_conf=0.9,
        timestamp_ms=now_ms(),
    )


def _args(mock_stt_response: str = "i am fine") -> argparse.Namespace:
    return argparse.Namespace(mock_stt=True, mock_stt_response=mock_stt_response)


async def _run_worker(
    cfg: RuntimeConfig,
    queue: "asyncio.Queue[FusionSnapshot]",
    status: CaregiverRuntimeStatus,
    dispatched: List[AlertPayload],
    *,
    inject_after_s: Optional[float],
    wait_s: float,
) -> None:
    """Drive the worker with a Tier-1 fall, optionally escalating mid-prompt."""
    stop = asyncio.Event()
    await queue.put(_snapshot(EmergencyTier.TIER_1_VERIFY, "A", "Fall detected."))
    worker = asyncio.create_task(_dispatch_worker(cfg, queue, _args(), stop, status))
    try:
        if inject_after_s is not None:
            await asyncio.sleep(inject_after_s)
            await queue.put(
                _snapshot(EmergencyTier.TIER_2_CARDIAC, "C", "Pulse signal lost.")
            )
        deadline = asyncio.get_event_loop().time() + wait_s
        while not dispatched and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.02)
    finally:
        stop.set()
        worker.cancel()
        try:
            await worker
        except (asyncio.CancelledError, Exception):
            pass


@pytest.fixture
def dispatched(monkeypatch) -> List[AlertPayload]:
    """Capture alert payloads instead of posting them."""
    seen: List[AlertPayload] = []

    async def _fake(self, payload: AlertPayload) -> str:
        seen.append(payload)
        return "sent"

    monkeypatch.setattr(WebhookDispatcher, "dispatch", _fake)
    return seen


def test_critical_vitals_during_verification_override_the_voice_reply(dispatched):
    """PRD escalation #3. The mock STT answers 'i am fine' at ~1.5 s; a pulse
    loss injected at 0.2 s must fire the cardiac alert before that, otherwise
    the subject is talked out of their own emergency."""
    cfg = RuntimeConfig()
    cfg.voice.verify_timeout_s = 3.0
    status = CaregiverRuntimeStatus()
    queue: "asyncio.Queue[FusionSnapshot]" = asyncio.Queue(maxsize=16)

    asyncio.run(
        _run_worker(cfg, queue, status, dispatched, inject_after_s=0.2, wait_s=1.2)
    )

    assert dispatched, "cardiac escalation never fired during verification"
    assert dispatched[0].tier == EmergencyTier.TIER_2_CARDIAC.value
    assert status.voice_status == "not_required"


def test_disabled_voice_escalates_tier_1_instead_of_prompting(dispatched):
    """`voice.enabled: false` must not silently keep prompting, and must not
    swallow the fall either - an unverified fall still alerts."""
    cfg = RuntimeConfig()
    cfg.voice.enabled = False
    status = CaregiverRuntimeStatus()
    queue: "asyncio.Queue[FusionSnapshot]" = asyncio.Queue(maxsize=16)

    asyncio.run(
        _run_worker(cfg, queue, status, dispatched, inject_after_s=None, wait_s=1.0)
    )

    assert dispatched, "Tier 1 was dropped when voice verification was disabled"
    assert dispatched[0].tier == EmergencyTier.TIER_1_VERIFY.value
    assert status.voice_status == "not_required"
