"""Action-logits ↔ fusion-engine wiring tests (Phase 1).

These cover the new ``action_logits`` argument on ``pose_signature`` and
the ``actions`` queue on ``FusionEngine``. The four scenarios in
``tests/test_fusion_rules.py`` continue to pass through the legacy
``action_logits=None`` path; these tests add the temporal-head-driven
behaviours that wiring enables.
"""

from __future__ import annotations

import asyncio
from typing import List

import pytest

from kineticpulse.config import RuntimeConfig, ThresholdsConfig
from kineticpulse.fusion.engine import FusionEngine, FusionSnapshot
from kineticpulse.fusion.rules import (
    AccelSignature,
    HrAggregate,
    HrSignature,
    PoseSignature,
    accel_signature,
    hr_signature,
    pose_signature,
)
from kineticpulse.fusion.tiers import EmergencyTier, classify
from kineticpulse.sensors.parser import AccelSample, HrSample, SensorEvent
from kineticpulse.temporal.types import ActionLogits
from kineticpulse.vision.detector import Detection, PostureClass
from kineticpulse.vision.features import PoseFeatures


# --------------------------------------------------------------------------- #
# pose_signature with action_logits
# --------------------------------------------------------------------------- #


def _logits(fallen=0.0, falling=0.0, stand=0.0, sitting=0.0, *, stable=None):
    return ActionLogits(
        fallen=fallen,
        falling=falling,
        stand=stand,
        sitting=sitting,
        timestamp_ms=0,
        stable_label=stable,
    )


def test_action_stable_label_overrides_static_detector_class():
    """When the temporal head has a stable label, it wins regardless of
    the per-frame YOLO detector class. This is the live-test failure
    mode we saw on the laptop webcam: detector said 'stand' but the
    person was clearly sitting — TSSTG corrects it."""
    sig = pose_signature(
        detector_class="stand",                # static detector wrong
        torso_angle_deg=20.0,
        aspect_ratio=0.7,
        centroid_vel_pps=10.0,
        action_logits=_logits(sitting=0.82, stand=0.10, stable="sitting"),
    )
    # 'sitting' resolves to UPRIGHT under stable vitals (Scenario D path).
    assert sig == PoseSignature.UPRIGHT


def test_action_high_confidence_overrides_without_stable_label():
    """Warm-up window: hysteresis hasn't latched yet, but raw argmax
    confidence is well above the threshold. We still trust the action
    head over the static detector."""
    sig = pose_signature(
        detector_class="stand",
        torso_angle_deg=70.0,
        aspect_ratio=1.5,
        centroid_vel_pps=500.0,
        action_logits=_logits(falling=0.74, stand=0.20, stable=None),
        action_confidence_threshold=0.55,
    )
    assert sig == PoseSignature.FALLING


def test_action_low_confidence_falls_back_to_detector():
    """If the temporal head is genuinely ambiguous (no class above the
    threshold and no stable label), don't override the static detector."""
    sig = pose_signature(
        detector_class="stand",
        torso_angle_deg=10.0,
        aspect_ratio=0.5,
        centroid_vel_pps=0.0,
        action_logits=_logits(falling=0.40, stand=0.35, sitting=0.20, stable=None),
        action_confidence_threshold=0.55,
    )
    # Detector says stand and the action head can't outrank it -> upright.
    assert sig == PoseSignature.UPRIGHT


def test_action_none_preserves_legacy_behaviour():
    """Existing test_fusion_rules.py callers pass action_logits=None.
    Must remain byte-compatible."""
    sig = pose_signature(
        detector_class="fallen",
        torso_angle_deg=85.0,
        aspect_ratio=2.5,
        centroid_vel_pps=0.0,
        action_logits=None,
    )
    assert sig == PoseSignature.PRONE


def test_action_promotes_scenario_a_when_detector_misses_falling():
    """Detector says 'stand' (e.g. label noise / motion blur), but TSSTG
    catches the fall via temporal context. Combined with an impact
    signature, this must still escalate to Tier 1 verify."""
    pose = pose_signature(
        detector_class="stand",
        torso_angle_deg=70.0,
        aspect_ratio=1.5,
        centroid_vel_pps=500.0,
        action_logits=_logits(falling=0.75, stand=0.15, stable="falling"),
    )
    assert pose == PoseSignature.FALLING

    # Synthetic impact: single 4 g spike at t=0.4 s (hz=50, 2 s window).
    accel_window: List[AccelSample] = []
    for i in range(100):
        ts = i * 20
        if i == 20:
            accel_window.append(AccelSample(4.0, 0.5, 1.0, ts))
        else:
            accel_window.append(AccelSample(0.0, 0.0, 1.0, ts))
    accel = accel_signature(accel_window, ThresholdsConfig())
    assert accel == AccelSignature.IMPACT_ONLY

    hr = hr_signature(HrAggregate(latest_bpm=115), ThresholdsConfig())
    decision = classify(pose, accel, hr)
    assert decision.tier == EmergencyTier.TIER_1_VERIFY
    assert decision.scenario == "A"


def test_action_fallen_promotes_when_static_says_stand():
    """TSSTG sees 'fallen' (with high enough torso tilt + AR for the
    PRONE branch); detector still says 'stand'. The action head must
    promote this into PRONE so a Scenario C / B path can fire."""
    sig = pose_signature(
        detector_class="stand",
        torso_angle_deg=85.0,
        aspect_ratio=2.5,
        centroid_vel_pps=0.0,
        action_logits=_logits(fallen=0.78, falling=0.10, stable="fallen"),
    )
    assert sig == PoseSignature.PRONE


# --------------------------------------------------------------------------- #
# FusionEngine: actions queue is consumed and reflected in snapshots
# --------------------------------------------------------------------------- #


def _build_engine_with_queues():
    cfg = RuntimeConfig()
    detections_q: "asyncio.Queue[Detection]" = asyncio.Queue(maxsize=8)
    features_q: "asyncio.Queue[PoseFeatures]" = asyncio.Queue(maxsize=8)
    sensor_q: "asyncio.Queue[SensorEvent]" = asyncio.Queue(maxsize=64)
    snapshots_q: "asyncio.Queue[FusionSnapshot]" = asyncio.Queue(maxsize=4)
    actions_q: "asyncio.Queue[ActionLogits]" = asyncio.Queue(maxsize=8)
    engine = FusionEngine(
        cfg=cfg,
        detections=detections_q,
        features=features_q,
        sensor_events=sensor_q,
        snapshots=snapshots_q,
        actions=actions_q,
        evaluate_every_ms=20,
    )
    return engine, detections_q, features_q, sensor_q, snapshots_q, actions_q


def test_fusion_engine_consumes_action_logits_and_publishes_in_snapshot():
    """Push a 'sitting' action directly into the engine's actions queue;
    after one evaluation cycle the snapshot must surface it."""

    async def _scenario():
        engine, _det_q, _feat_q, _sens_q, snap_q, actions_q = _build_engine_with_queues()
        await actions_q.put(_logits(sitting=0.80, stand=0.10, stable="sitting"))
        task = asyncio.create_task(engine.run())
        try:
            snap = await asyncio.wait_for(snap_q.get(), timeout=2.0)
        finally:
            engine.stop()
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        return snap

    snap = asyncio.run(_scenario())
    assert snap.action_class == "sitting"
    assert snap.action_conf is not None and snap.action_conf >= 0.79


def test_fusion_engine_works_without_actions_queue_legacy():
    """Constructing FusionEngine with actions=None must keep the
    pre-Phase-1 behaviour: fusion still emits snapshots, just with
    action_class=None. Backwards compatibility guard."""

    async def _scenario():
        cfg = RuntimeConfig()
        detections_q: "asyncio.Queue[Detection]" = asyncio.Queue(maxsize=8)
        features_q: "asyncio.Queue[PoseFeatures]" = asyncio.Queue(maxsize=8)
        sensor_q: "asyncio.Queue[SensorEvent]" = asyncio.Queue(maxsize=64)
        snapshots_q: "asyncio.Queue[FusionSnapshot]" = asyncio.Queue(maxsize=4)

        engine = FusionEngine(
            cfg=cfg,
            detections=detections_q,
            features=features_q,
            sensor_events=sensor_q,
            snapshots=snapshots_q,
            actions=None,
            evaluate_every_ms=20,
        )
        task = asyncio.create_task(engine.run())
        try:
            snap = await asyncio.wait_for(snapshots_q.get(), timeout=2.0)
        finally:
            engine.stop()
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        return snap

    snap = asyncio.run(_scenario())
    assert snap.action_class is None
    assert snap.action_conf is None
