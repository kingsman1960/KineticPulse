"""One test per PRD section 5 scenario, exercising the rule + tier pipeline."""

from __future__ import annotations

import math
from typing import List

import pytest

from kineticpulse.config import ThresholdsConfig
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
from kineticpulse.sensors.parser import AccelSample, HrSample


def _thresholds() -> ThresholdsConfig:
    return ThresholdsConfig()


def _accel_quiet(n: int = 100, hz: int = 50) -> List[AccelSample]:
    return [AccelSample(0.0, 0.0, 1.0, i * int(1000 / hz)) for i in range(n)]


def _accel_impact_then_still(hz: int = 50, total_s: float = 2.0) -> List[AccelSample]:
    """A single 4 g spike at t=0.4 s, then quiet."""
    samples: List[AccelSample] = []
    total = int(total_s * hz)
    impact_idx = int(0.4 * hz)
    for i in range(total):
        if i == impact_idx:
            samples.append(AccelSample(4.0, 0.5, 1.0, i * int(1000 / hz)))
        else:
            samples.append(AccelSample(0.0, 0.0, 1.0, i * int(1000 / hz)))
    return samples


def _accel_impact_then_tremor(hz: int = 50, total_s: float = 3.0,
                              tremor_hz: float = 5.0) -> List[AccelSample]:
    """4 g impact at t=0.4 s, then sustained ~5 Hz tremor for the rest."""
    samples: List[AccelSample] = []
    total = int(total_s * hz)
    impact_idx = int(0.4 * hz)
    for i in range(total):
        t = i / hz
        if i == impact_idx:
            samples.append(AccelSample(5.0, 0.0, 1.0, i * int(1000 / hz)))
            continue
        if i > impact_idx:
            ac = 0.4 * math.sin(2 * math.pi * tremor_hz * (t - impact_idx / hz))
            samples.append(AccelSample(ac, ac, 1.0 + ac, i * int(1000 / hz)))
        else:
            samples.append(AccelSample(0.0, 0.0, 1.0, i * int(1000 / hz)))
    return samples


def _accel_soft_collapse(hz: int = 50, total_s: float = 2.0) -> List[AccelSample]:
    """Sustained sub-threshold activity (~1.85 g peak) over ~0.6 s; what a
    syncope/cardiac collapse looks like on the wristband - no sharp impact,
    but the limb is moving as the body slumps."""
    samples: List[AccelSample] = []
    total = int(total_s * hz)
    collapse_start = int(0.3 * hz)
    collapse_end = int(0.9 * hz)
    for i in range(total):
        if collapse_start <= i < collapse_end:
            samples.append(AccelSample(1.0, 0.5, 1.5, i * int(1000 / hz)))
        else:
            samples.append(AccelSample(0.0, 0.0, 1.0, i * int(1000 / hz)))
    return samples


# --------------------------------------------------------------------------- #
# Scenario A - standard fall -> Tier 1, voice verification
# --------------------------------------------------------------------------- #


def test_scenario_a_standard_fall_triggers_tier_1_verify() -> None:
    pose = pose_signature(
        detector_class="falling",
        torso_angle_deg=70.0,
        aspect_ratio=1.5,
        centroid_vel_pps=500.0,
    )
    assert pose == PoseSignature.FALLING

    accel = accel_signature(_accel_impact_then_still(), _thresholds())
    assert accel == AccelSignature.IMPACT_ONLY

    hr = hr_signature(HrAggregate(latest_bpm=115), _thresholds())
    assert hr == HrSignature.PANIC_SPIKE

    decision = classify(pose, accel, hr)
    assert decision.tier == EmergencyTier.TIER_1_VERIFY
    assert decision.scenario == "A"
    assert not decision.tier.bypasses_voice


# --------------------------------------------------------------------------- #
# Scenario B - suspected seizure -> Tier 2, bypass voice
# --------------------------------------------------------------------------- #


def test_scenario_b_seizure_bypasses_voice() -> None:
    pose = pose_signature(
        detector_class="fallen",
        torso_angle_deg=85.0,
        aspect_ratio=2.5,
        centroid_vel_pps=0.0,
    )
    assert pose == PoseSignature.PRONE

    accel = accel_signature(_accel_impact_then_tremor(), _thresholds())
    assert accel == AccelSignature.IMPACT_TREMOR

    hr = hr_signature(HrAggregate(latest_bpm=150), _thresholds())
    assert hr == HrSignature.SEIZURE_SPIKE

    decision = classify(pose, accel, hr)
    assert decision.tier == EmergencyTier.TIER_2_SEIZURE
    assert decision.scenario == "B"
    assert decision.tier.bypasses_voice


# --------------------------------------------------------------------------- #
# Scenario C - syncope / cardiac arrest -> Tier 2, bypass voice
# --------------------------------------------------------------------------- #


def test_scenario_c_bradycardia_with_fall_bypasses_voice() -> None:
    pose = pose_signature(
        detector_class="fallen",
        torso_angle_deg=85.0,
        aspect_ratio=2.5,
        centroid_vel_pps=0.0,
    )
    assert pose == PoseSignature.PRONE

    accel = accel_signature(_accel_soft_collapse(), _thresholds())
    assert accel == AccelSignature.SOFT_COLLAPSE

    hr = hr_signature(HrAggregate(latest_bpm=42), _thresholds())
    assert hr == HrSignature.BRADYCARDIA

    decision = classify(pose, accel, hr)
    assert decision.tier == EmergencyTier.TIER_2_CARDIAC
    assert decision.scenario == "C"
    assert decision.tier.bypasses_voice


def test_scenario_c_pulse_lost_bypasses_voice() -> None:
    pose = pose_signature(
        detector_class="fallen",
        torso_angle_deg=85.0,
        aspect_ratio=2.5,
        centroid_vel_pps=0.0,
    )
    accel = accel_signature(_accel_soft_collapse(), _thresholds())
    hr = hr_signature(HrAggregate(latest_bpm=None, pulse_lost_s=5.0), _thresholds())
    assert hr == HrSignature.PULSE_LOST

    decision = classify(pose, accel, hr)
    assert decision.tier == EmergencyTier.TIER_2_CARDIAC
    assert decision.tier.bypasses_voice


# --------------------------------------------------------------------------- #
# Scenario D - false positive -> Tier 0, dismiss
# --------------------------------------------------------------------------- #


def test_scenario_d_bending_with_stable_vitals_is_dismissed() -> None:
    # CV briefly reports "fallen" but pose features say upright (torso 20 deg,
    # aspect ratio < 1) -> pose_signature overrules into UPRIGHT.
    pose = pose_signature(
        detector_class="fallen",
        torso_angle_deg=20.0,
        aspect_ratio=0.6,
        centroid_vel_pps=50.0,
    )
    assert pose == PoseSignature.UPRIGHT

    accel = accel_signature(_accel_quiet(), _thresholds())
    assert accel == AccelSignature.QUIET

    hr = hr_signature(HrAggregate(latest_bpm=72), _thresholds())
    assert hr == HrSignature.RESTING

    decision = classify(pose, accel, hr)
    assert decision.tier == EmergencyTier.TIER_0_DISMISS
    assert decision.scenario == "D"


# --------------------------------------------------------------------------- #
# Hardware degradation: no accelerometer (current build status)
# --------------------------------------------------------------------------- #


def test_no_accel_seizure_degrades_to_tier_1_verify() -> None:
    """Without IMU data, the seizure-specific Tier-2 path is unreachable
    (no impact + tremor signature). The system must degrade gracefully to
    Tier-1 voice verification instead of silently dropping the event.
    """
    pose = pose_signature(
        detector_class="fallen",
        torso_angle_deg=85.0,
        aspect_ratio=2.5,
        centroid_vel_pps=0.0,
    )
    assert pose == PoseSignature.PRONE

    # IMU missing -> empty accel window -> UNKNOWN signature.
    accel = accel_signature([], _thresholds())
    assert accel == AccelSignature.UNKNOWN

    # Same elevated HR as the seizure scenario.
    hr = hr_signature(HrAggregate(latest_bpm=150), _thresholds())
    assert hr == HrSignature.SEIZURE_SPIKE

    decision = classify(pose, accel, hr)
    assert decision.tier == EmergencyTier.TIER_1_VERIFY, (
        "Without IMU we cannot confirm seizure; system must still verify "
        "the fall rather than skip it."
    )
    assert decision.scenario == "A"
    assert not decision.tier.bypasses_voice


def test_no_accel_cardiac_path_still_bypasses_voice() -> None:
    """Cardiac / syncope detection is fully HR-driven and must still
    fire Tier 2 (bypass voice) even without the accelerometer."""
    pose = pose_signature(
        detector_class="fallen",
        torso_angle_deg=85.0,
        aspect_ratio=2.5,
        centroid_vel_pps=0.0,
    )
    accel = accel_signature([], _thresholds())   # no IMU
    assert accel == AccelSignature.UNKNOWN

    hr = hr_signature(HrAggregate(latest_bpm=None, pulse_lost_s=5.0), _thresholds())
    assert hr == HrSignature.PULSE_LOST

    decision = classify(pose, accel, hr)
    assert decision.tier == EmergencyTier.TIER_2_CARDIAC
    assert decision.tier.bypasses_voice
