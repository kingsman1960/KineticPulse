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
# Sitting (4-class schema) - should behave as non-fall under stable vitals
# --------------------------------------------------------------------------- #


def test_sitting_with_stable_vitals_is_dismissed() -> None:
    """A subject sitting calmly in a chair must not trigger any tier.
    Detector says 'sitting', pose features are upright-ish, accel is
    quiet, HR is resting -> Scenario D dismissal."""
    pose = pose_signature(
        detector_class="sitting",
        torso_angle_deg=20.0,
        aspect_ratio=0.7,
        centroid_vel_pps=15.0,
    )
    assert pose == PoseSignature.UPRIGHT

    accel = accel_signature(_accel_quiet(), _thresholds())
    assert accel == AccelSignature.QUIET

    hr = hr_signature(HrAggregate(latest_bpm=78), _thresholds())
    assert hr == HrSignature.RESTING

    decision = classify(pose, accel, hr)
    assert decision.tier == EmergencyTier.TIER_0_DISMISS
    assert decision.scenario == "D"


def test_sudden_seated_collapse_with_bradycardia_triggers_cardiac() -> None:
    """Subject was standing then dropped into a seated posture with a sharp
    torso tilt. Combined with bradycardia from the wristband this is the
    'syncope-while-sitting' edge case - it must still bypass voice."""
    pose = pose_signature(
        detector_class="sitting",
        torso_angle_deg=65.0,
        aspect_ratio=0.9,
        centroid_vel_pps=1.2,
    )
    assert pose == PoseSignature.FALLING

    accel = accel_signature(_accel_soft_collapse(), _thresholds())
    assert accel == AccelSignature.SOFT_COLLAPSE

    hr = hr_signature(HrAggregate(latest_bpm=42), _thresholds())
    assert hr == HrSignature.BRADYCARDIA

    decision = classify(pose, accel, hr)
    assert decision.tier == EmergencyTier.TIER_2_CARDIAC
    assert decision.scenario == "C"
    assert decision.tier.bypasses_voice


def test_walking_wrist_swing_is_quiet_not_soft_collapse() -> None:
    """Arm swing peaks around 2 g continuously. That used to match
    SOFT_COLLAPSE (peak in [1.8, 3)); the tail is still moving so it
    must stay QUIET."""
    samples: List[AccelSample] = []
    hz, total_s = 50, 2.0
    for i in range(int(total_s * hz)):
        t = i / hz
        swing = 1.6 * math.sin(2 * math.pi * 2.0 * t)
        samples.append(AccelSample(swing, 0.4, 1.0, i * int(1000 / hz)))
    peak = max(s.magnitude_g for s in samples)
    assert peak >= 1.8
    assert accel_signature(samples, _thresholds()) == AccelSignature.QUIET


def test_tremor_signature_needs_window_longer_than_min_duration() -> None:
    """FusionEngine used to pass a 2 s slice while tremor_min is 2 s, so
    the post-impact tail could never qualify. A 4 s window that still
    contains the impact does; a 2 s slice of the same recording does not.
    """
    samples = _accel_impact_then_tremor(total_s=4.0)
    end = samples[-1].timestamp_ms
    short = [s for s in samples if s.timestamp_ms >= end - 2000]
    long = [s for s in samples if s.timestamp_ms >= end - 4000]
    assert accel_signature(short, _thresholds()) != AccelSignature.IMPACT_TREMOR
    assert accel_signature(long, _thresholds()) == AccelSignature.IMPACT_TREMOR


def test_still_bbox_jitter_does_not_promote_stand_to_falling() -> None:
    pose = pose_signature(
        detector_class="stand",
        torso_angle_deg=50.0,
        aspect_ratio=0.8,
        centroid_vel_pps=1.5,
        stillness=0.95,
    )
    assert pose == PoseSignature.UPRIGHT


def test_fallen_fidget_with_mid_torso_is_false_positive() -> None:
    pose = pose_signature(
        detector_class="fallen",
        torso_angle_deg=40.0,
        aspect_ratio=0.9,
        centroid_vel_pps=0.2,
        stillness=0.1,
    )
    assert pose == PoseSignature.FALSE_POSITIVE


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


# --------------------------------------------------------------------------- #
# Partial framing: torso_angle_deg is None (hips/shoulders out of frame)
# --------------------------------------------------------------------------- #


def test_stand_with_no_torso_angle_still_detects_descent() -> None:
    """Subject collapses while only the upper body is framed, so the pose
    estimator cannot resolve hips and torso_angle_deg is None. The angle-gated
    rules all degrade to UPRIGHT, so bbox kinematics must carry the call."""
    pose = pose_signature(
        detector_class="stand",
        torso_angle_deg=None,
        aspect_ratio=0.8,
        centroid_vel_pps=1.4,
        stillness=0.1,
    )
    assert pose == PoseSignature.FALLING


def test_sitting_collapse_with_no_torso_angle_is_detected() -> None:
    """The reported failure mode: subject slumps out of a chair while framed
    close to the lens. Detector says 'sitting', no torso angle available."""
    pose = pose_signature(
        detector_class="sitting",
        torso_angle_deg=None,
        aspect_ratio=0.9,
        centroid_vel_pps=1.1,
        stillness=0.15,
    )
    assert pose == PoseSignature.FALLING


def test_no_torso_angle_wide_bbox_lowers_the_descent_bar() -> None:
    """A bbox already wider than tall needs less measured drop to be credible."""
    slow_descent = 0.7
    assert pose_signature(
        detector_class="stand", torso_angle_deg=None,
        aspect_ratio=1.4, centroid_vel_pps=slow_descent, stillness=0.1,
    ) == PoseSignature.FALLING
    # Same descent with an upright-shaped bbox stays below the bar.
    assert pose_signature(
        detector_class="stand", torso_angle_deg=None,
        aspect_ratio=0.7, centroid_vel_pps=slow_descent, stillness=0.1,
    ) == PoseSignature.UPRIGHT


def test_no_torso_angle_still_subject_is_not_promoted() -> None:
    """Fallback must not fire on a still subject - that is bbox jitter, and a
    false tier_1 wakes the resident with a voice prompt for nothing."""
    pose = pose_signature(
        detector_class="stand",
        torso_angle_deg=None,
        aspect_ratio=0.8,
        centroid_vel_pps=1.4,
        stillness=0.95,
    )
    assert pose == PoseSignature.UPRIGHT


def test_no_torso_angle_without_velocity_is_not_promoted() -> None:
    """No measured descent means no fall claim, however wide the bbox is."""
    pose = pose_signature(
        detector_class="stand",
        torso_angle_deg=None,
        aspect_ratio=1.6,
        centroid_vel_pps=None,
        stillness=0.1,
    )
    assert pose == PoseSignature.UPRIGHT


def test_no_angle_fallback_cannot_reach_the_seizure_tier() -> None:
    """The fallback yields FALLING, never PRONE, so it cannot satisfy the
    Scenario B seizure rule (which requires PRONE + IMPACT_TREMOR).

    FALLING on its own is not voice-safe - with bradycardia or pulse loss it
    still escalates to tier_2_cardiac and bypasses voice. That is intended:
    those HR states are independent evidence, not a vision artefact.
    """
    pose = pose_signature(
        detector_class="stand", torso_angle_deg=None,
        aspect_ratio=1.5, centroid_vel_pps=2.0, stillness=0.1,
    )
    assert pose == PoseSignature.FALLING

    # Stable/absent vitals: the fallback alone only ever asks for verification.
    for hr in (HrSignature.RESTING, HrSignature.UNKNOWN):
        decision = classify(pose, AccelSignature.UNKNOWN, hr)
        assert decision.tier == EmergencyTier.TIER_1_VERIFY
        assert not decision.tier.bypasses_voice

    # Yielding FALLING rather than PRONE keeps the PRONE-gated seizure rule
    # out of reach: the same accel/HR pair escalates to a voice-bypassing
    # seizure tier under PRONE, but only to tier_1_verify under FALLING.
    # (The other seizure rule ignores pose entirely, so the fallback cannot
    # influence it in either direction.)
    as_falling = classify(pose, AccelSignature.IMPACT_TREMOR, HrSignature.PANIC_SPIKE)
    assert as_falling.tier == EmergencyTier.TIER_1_VERIFY
    assert not as_falling.tier.bypasses_voice
    as_prone = classify(
        PoseSignature.PRONE, AccelSignature.IMPACT_TREMOR, HrSignature.PANIC_SPIKE
    )
    assert as_prone.scenario == "B"


def test_angle_present_keeps_tuned_rules_authoritative() -> None:
    """When the estimator does give an angle, the fallback must stay out of
    the way - a small torso angle still means upright even at high velocity."""
    pose = pose_signature(
        detector_class="stand",
        torso_angle_deg=15.0,
        aspect_ratio=0.6,
        centroid_vel_pps=3.0,
        stillness=0.1,
    )
    assert pose == PoseSignature.UPRIGHT
