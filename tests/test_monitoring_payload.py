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
    )
    assert payload["subject_id"] == "resident-001"
    assert payload["sensor"]["connection"] == "connected"
    assert payload["snapshot"]["latest_hr_bpm"] == 72
    assert payload["snapshot"]["accel"] == "quiet"
    assert payload["snapshot"]["decision"]["tier"] == "none"
    assert payload["snapshot"]["detector_class"] == "stand"
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
