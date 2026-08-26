"""Monitoring wire payload shape for the caregiver dashboard."""

from __future__ import annotations

from kineticpulse.config import AlertsConfig
from kineticpulse.fusion.engine import FusionSnapshot
from kineticpulse.fusion.rules import AccelSignature, HrSignature, PoseSignature
from kineticpulse.fusion.tiers import EmergencyTier, TierDecision
from kineticpulse.monitoring.http import build_monitoring_payload


class _FakeSensors:
    def __init__(self, connected: bool) -> None:
        self.connected = connected


def test_monitoring_payload_mirrors_fusion_snapshot():
    snap = FusionSnapshot(
        decision=TierDecision(
            tier=EmergencyTier.NONE,
            scenario="monitoring",
            reason="No fall signatures detected.",
        ),
        pose=PoseSignature.UPRIGHT,
        accel=AccelSignature.QUIET,
        hr=HrSignature.RESTING,
        latest_hr_bpm=72,
        latest_accel_g=1.01,
        detector_class="stand",
        detector_conf=0.96,
        action_class="stand",
        action_conf=0.93,
        timestamp_ms=1_770_000_000_000,
    )
    payload = build_monitoring_payload(
        alerts=AlertsConfig(subject_id="resident-001", location="Living room"),
        snapshot=snap,
        sensors=_FakeSensors(True),
        published_at_ms=1_780_000_000_000,
    )
    assert payload["subject_id"] == "resident-001"
    assert payload["sensor"]["connection"] == "connected"
    assert payload["snapshot"]["latest_hr_bpm"] == 72
    assert payload["snapshot"]["accel"] == "quiet"
    assert payload["snapshot"]["decision"]["tier"] == "none"
    assert payload["snapshot"]["detector_class"] == "stand"
    assert payload["snapshot"]["timestamp_ms"] == 1_780_000_000_000
    assert payload["voice"]["status"] == "not_required"
    assert payload["alert_dispatch"]["status"] == "idle"


def test_monitoring_payload_warm_up_and_disconnected_sensor():
    payload = build_monitoring_payload(
        alerts=AlertsConfig(subject_id="s", location="x"),
        snapshot=None,
        sensors=_FakeSensors(False),
    )
    assert payload["sensor"]["connection"] == "disconnected"
    assert payload["snapshot"]["latest_hr_bpm"] is None
    assert payload["snapshot"]["decision"]["tier"] == "none"


def test_monitoring_payload_carries_voice_alert_and_events():
    events = [
        {
            "id": "runtime-1",
            "timestamp_ms": 1,
            "severity": "warning",
            "category": "fusion",
            "title": "Emergency tier_1_verify",
            "detail": "fall",
        }
    ]
    payload = build_monitoring_payload(
        alerts=AlertsConfig(subject_id="s", location="x"),
        snapshot=None,
        sensors=_FakeSensors(True),
        voice_status="pending",
        alert_dispatch_status="sent",
        events=events,
    )
    assert payload["voice"]["status"] == "pending"
    assert payload["alert_dispatch"]["status"] == "sent"
    assert payload["events"][0]["title"].startswith("Emergency")


def test_session_meta_includes_vitals():
    from kineticpulse.webrtc.session_meta import build_session_meta

    snap = FusionSnapshot(
        decision=TierDecision(
            tier=EmergencyTier.TIER_1_VERIFY,
            scenario="A",
            reason="standard fall",
        ),
        pose=PoseSignature.PRONE,
        accel=AccelSignature.IMPACT_ONLY,
        hr=HrSignature.PANIC_SPIKE,
        latest_hr_bpm=118,
        latest_accel_g=2.4,
        detector_class="fallen",
        detector_conf=0.9,
        action_class="fallen",
        action_conf=0.8,
        timestamp_ms=42,
    )
    meta = build_session_meta(
        session_id="kp-1",
        subject_id="s",
        location="lab",
        snapshot=snap,
        extra={"voice_verdict": "distress"},
    )
    d = meta.as_dict()
    assert d["heart_rate_bpm"] == 118
    assert d["hr_signature"] == "panic_spike"
    assert d["accel_magnitude_g"] == 2.4
    assert d["extra"]["voice_verdict"] == "distress"
