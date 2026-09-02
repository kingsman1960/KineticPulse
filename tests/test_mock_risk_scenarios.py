"""Realistic dashboard playbooks: trip, night syncope, tonic-clonic, silent slump."""

from __future__ import annotations

from kineticpulse.config import ThresholdsConfig
from kineticpulse.fusion.rules import accel_signature, hr_signature, pose_signature, HrAggregate
from kineticpulse.fusion.tiers import EmergencyTier, classify
from kineticpulse.sensors.mock import (
    DEMO_CLI,
    DEMO_NIGHT_SYNCOPE,
    DEMO_SILENT_SLUMP,
    DEMO_TONIC_CLONIC,
    DEMO_TRIP_FALL,
    MOCK_SCENARIOS,
    NIGHT_CRUMPLE_S,
    NIGHT_PULSE_LOST_S,
    SLUMP_S,
    TONIC_DROP_S,
    TRIP_IMPACT_S,
    demo_accel,
    demo_hr,
    demo_posture,
)
from kineticpulse.sensors.parser import AccelSample


def _mag(ax: float, ay: float, az: float) -> float:
    return (ax * ax + ay * ay + az * az) ** 0.5


def _window(scenario: str, t0: float, seconds: float = 4.0, hz: int = 50):
    samples = []
    n = int(seconds * hz)
    for i in range(n):
        t_s = t0 + i / hz
        ax, ay, az = demo_accel(scenario, t_s, 0.0)
        samples.append(AccelSample(ax=ax, ay=ay, az=az, timestamp_ms=int(t_s * 1000)))
    return samples


def _prone():
    return pose_signature("fallen", 80.0, 2.0, 0.0, stillness=0.9)


def test_demo_cli_names_are_mock_scenarios():
    assert set(DEMO_CLI.values()) <= set(MOCK_SCENARIOS)


def test_trip_fall_is_impact_then_panic_not_seizure():
    rest = demo_accel(DEMO_TRIP_FALL, 2.0, 0.0)
    assert abs(_mag(*rest) - 1.0) < 0.05
    hit = demo_accel(DEMO_TRIP_FALL, TRIP_IMPACT_S + 0.05, 0.0)
    assert _mag(*hit) >= 3.0
    still = demo_accel(DEMO_TRIP_FALL, TRIP_IMPACT_S + 2.0, 0.0)
    assert abs(_mag(*still) - 1.0) < 0.05
    hr = demo_hr(DEMO_TRIP_FALL, TRIP_IMPACT_S + 4.0)
    assert hr is not None and 100 <= hr < 130
    assert demo_posture(DEMO_TRIP_FALL, 1.0) == "stand"
    assert demo_posture(DEMO_TRIP_FALL, TRIP_IMPACT_S + 1.0) == "fallen"
    accel = accel_signature(_window(DEMO_TRIP_FALL, TRIP_IMPACT_S, 3.0), ThresholdsConfig())
    assert accel.value == "impact"
    decision = classify(
        _prone(), accel, hr_signature(HrAggregate(latest_bpm=hr), ThresholdsConfig())
    )
    assert decision.tier == EmergencyTier.TIER_1_VERIFY


def test_night_syncope_crumples_then_loses_pulse():
    assert demo_posture(DEMO_NIGHT_SYNCOPE, 2.0) == "sitting"
    assert demo_posture(DEMO_NIGHT_SYNCOPE, 9.0) == "stand"
    assert demo_posture(DEMO_NIGHT_SYNCOPE, NIGHT_CRUMPLE_S + 1.0) == "fallen"
    pre = demo_hr(DEMO_NIGHT_SYNCOPE, 10.5)
    assert pre is not None and pre < 50
    assert demo_hr(DEMO_NIGHT_SYNCOPE, NIGHT_PULSE_LOST_S + 0.5) is None
    crumple = demo_accel(DEMO_NIGHT_SYNCOPE, NIGHT_CRUMPLE_S + 0.2, 0.0)
    assert 1.8 <= _mag(*crumple) < 3.0
    accel = accel_signature(_window(DEMO_NIGHT_SYNCOPE, NIGHT_CRUMPLE_S, 2.0), ThresholdsConfig())
    assert accel.value == "soft_collapse"
    hr = hr_signature(HrAggregate(latest_bpm=pre, pulse_lost_s=0.0), ThresholdsConfig())
    decision = classify(_prone(), accel, hr)
    assert decision.tier == EmergencyTier.TIER_2_CARDIAC


def test_tonic_clonic_classifies_as_seizure():
    assert demo_hr(DEMO_TONIC_CLONIC, 5.0) is not None
    late = demo_hr(DEMO_TONIC_CLONIC, TONIC_DROP_S + 3.0)
    assert late is not None and late >= 130
    accel = accel_signature(_window(DEMO_TONIC_CLONIC, TONIC_DROP_S, 4.0), ThresholdsConfig())
    assert accel.value == "impact_tremor"
    hr = hr_signature(HrAggregate(latest_bpm=late), ThresholdsConfig())
    decision = classify(_prone(), accel, hr)
    assert decision.tier == EmergencyTier.TIER_2_SEIZURE


def test_silent_slump_has_no_hard_impact():
    assert demo_posture(DEMO_SILENT_SLUMP, 2.0) == "sitting"
    assert demo_posture(DEMO_SILENT_SLUMP, SLUMP_S + 1.0) == "fallen"
    peak = max(
        _mag(*demo_accel(DEMO_SILENT_SLUMP, SLUMP_S + i * 0.02, 0.0))
        for i in range(80)
    )
    assert peak < 3.0
    hr = demo_hr(DEMO_SILENT_SLUMP, SLUMP_S + 2.0)
    assert hr is not None and hr < 100
    accel = accel_signature(_window(DEMO_SILENT_SLUMP, SLUMP_S, 3.0), ThresholdsConfig())
    assert accel.value in ("quiet", "soft_collapse")
    decision = classify(
        _prone(), accel, hr_signature(HrAggregate(latest_bpm=hr), ThresholdsConfig())
    )
    assert decision.tier == EmergencyTier.TIER_1_VERIFY
    assert not decision.tier.bypasses_voice
