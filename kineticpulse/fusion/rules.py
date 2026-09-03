"""Rule primitives that summarise raw modality signals into signatures.

Each ``*_signature`` function reduces a short window of samples to a
small enum-like dataclass. The tier classifier in :mod:`tiers` consumes
these signatures - never the raw samples - so the rules are testable
in isolation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Sequence

from kineticpulse.config import ThresholdsConfig
from kineticpulse.sensors.parser import AccelSample, HrSample, PulseLost, SensorEvent
from kineticpulse.temporal.types import ActionLogits

# ponytail: centroid_vel is bbox-normalized (body-lengths / s). ~1.0 is a
# full-height drop in one second. Upgrade: per-camera calibration.
_FALL_VEL_BLS = 1.0
_SIT_COLLAPSE_VEL_BLS = 0.85
_STILLNESS_HIGH = 0.7   # 1/(1+std); still window in tests is > 0.9
_STILLNESS_LOW = 0.3    # moving window in tests is < 0.2
_SOFT_COLLAPSE_G = 1.8
_SOFT_COLLAPSE_MIN_S = 0.3
_TAIL_STILL_MS = 400
_AC_QUIET = 0.15


# --------------------------------------------------------------------------- #
# Pose signature
# --------------------------------------------------------------------------- #


class PoseSignature(str, Enum):
    """Coarse posture summary derived from the trained YOLOv8 detector +
    pose features."""

    UNKNOWN = "unknown"
    UPRIGHT = "upright"
    FALLING = "falling"            # mid-fall transition
    PRONE = "prone"                # subject is on the ground
    FALSE_POSITIVE = "false_pos"   # CV anomaly that the pose features overrule


def pose_signature(
    detector_class: Optional[str],
    torso_angle_deg: Optional[float],
    aspect_ratio: Optional[float],
    centroid_vel_pps: Optional[float],
    action_logits: Optional[ActionLogits] = None,
    action_confidence_threshold: float = 0.55,
    stillness: Optional[float] = None,
) -> PoseSignature:
    """Combine the detector class with the pose-feature triple.

    The detector class is the strongest signal; the pose features promote
    or demote borderline cases (PRD section 5.4 false-positive override).

    ``sitting`` is treated as a non-fall posture by default (Scenario D
    candidate). It only escalates if the pose features show a sudden
    descent with body tilt - that pattern is consistent with a syncope
    collapse where the subject's last conscious motion is to drop into a
    seated position. The actual escalation decision is still made by the
    classifier in ``tiers.py`` once accel/HR are folded in.

    When ``action_logits`` is provided (TSSTG temporal head), it
    overrides the static detector class in two cases:

    1. ``action_logits.stable_label`` is set (i.e. the temporal head has
       held the same label for ``hysteresis_min_consecutive`` predictions
       in a row) -> use the stable label. This is the production path.
    2. No stable label yet, but the raw argmax probability is at least
       ``action_confidence_threshold`` -> use the raw argmax. Useful for
       the warm-up window before hysteresis settles.

    The temporal head's 4 classes are byte-compatible with the detector
    classes (``fallen``, ``falling``, ``stand``, ``sitting``), so the
    rest of the function is unchanged.
    """
    effective_class = detector_class
    if action_logits is not None:
        if action_logits.stable_label is not None:
            effective_class = action_logits.stable_label
        else:
            ax = action_logits.argmax_label
            if action_logits.confidence_of(ax) >= action_confidence_threshold:
                effective_class = ax
    still = stillness is not None and stillness >= _STILLNESS_HIGH
    fidgeting = stillness is not None and stillness < _STILLNESS_LOW

    cls = (effective_class or "").lower()
    if cls == "fallen":
        if (torso_angle_deg is not None and torso_angle_deg < 30
                and (aspect_ratio is None or aspect_ratio < 1.0)):
            return PoseSignature.UPRIGHT
        # Detector says fallen but the skeleton is fidgeting upright-ish —
        # not a grounded body. Horizontal + moving stays PRONE (seizure).
        if fidgeting and torso_angle_deg is not None and torso_angle_deg < 50:
            return PoseSignature.FALSE_POSITIVE
        return PoseSignature.PRONE
    if cls == "falling":
        # v2 labels a still chair-sitter as falling. Same override as
        # fallen→UPRIGHT: upright + tall box + not actually moving.
        # Missing pose features keep FALLING (demos / first frames).
        upright = torso_angle_deg is not None and torso_angle_deg < 35
        tall = aspect_ratio is None or aspect_ratio < 1.0
        slow = still or (
            centroid_vel_pps is not None and abs(centroid_vel_pps) < _FALL_VEL_BLS
        )
        if upright and tall and slow:
            return PoseSignature.UPRIGHT
        return PoseSignature.FALLING
    if cls == "stand":
        if (centroid_vel_pps is not None and centroid_vel_pps > _FALL_VEL_BLS
                and torso_angle_deg is not None and torso_angle_deg > 45
                and not still):
            return PoseSignature.FALLING
        if (torso_angle_deg is not None and torso_angle_deg > 70
                and aspect_ratio is not None and aspect_ratio > 1.0):
            return PoseSignature.PRONE
        return PoseSignature.UPRIGHT
    if cls == "sitting":
        # Sudden seated drop with marked tilt - possible syncope.
        # High stillness = bbox jitter, not a collapse.
        if (centroid_vel_pps is not None and centroid_vel_pps > _SIT_COLLAPSE_VEL_BLS
                and torso_angle_deg is not None and torso_angle_deg > 50
                and not still):
            return PoseSignature.FALLING
        # Otherwise sitting is just a non-fall posture; fusion treats it the
        # same as standing for Scenario D dismissal but the engine still
        # records the distinct class for downstream analytics.
        return PoseSignature.UPRIGHT
    return PoseSignature.UNKNOWN


# --------------------------------------------------------------------------- #
# Accelerometer signature
# --------------------------------------------------------------------------- #


class AccelSignature(str, Enum):
    UNKNOWN = "unknown"
    QUIET = "quiet"                # baseline gravity only
    IMPACT_ONLY = "impact"         # single high-G peak, then quiet
    IMPACT_TREMOR = "impact_tremor"  # impact + rhythmic oscillations (Scenario B)
    SOFT_COLLAPSE = "soft_collapse"  # gradual fall, no sharp impact (Scenario C)


def _peak_magnitude(window: Sequence[AccelSample]) -> float:
    return max((s.magnitude_g for s in window), default=0.0)


def _dominant_frequency_hz(window: Sequence[AccelSample]) -> Optional[float]:
    """Naive zero-crossing-based frequency estimate for the AC component
    of the accelerometer magnitude (no SciPy dependency)."""
    if len(window) < 8:
        return None
    samples = [s.magnitude_g - 1.0 for s in window]
    crossings = 0
    for i in range(1, len(samples)):
        if (samples[i - 1] <= 0 < samples[i]) or (samples[i - 1] > 0 >= samples[i]):
            crossings += 1
    duration_s = max(1e-3, (window[-1].timestamp_ms - window[0].timestamp_ms) / 1000.0)
    return (crossings / 2.0) / duration_s


def _ac_amplitude(window: Sequence[AccelSample]) -> float:
    if not window:
        return 0.0
    deviations = [abs(s.magnitude_g - 1.0) for s in window]
    return sum(deviations) / len(deviations)


def _is_soft_collapse(window: Sequence[AccelSample], peak: float) -> bool:
    """Sub-threshold slump then stillness. Walking stays noisy in the tail."""
    if peak < _SOFT_COLLAPSE_G:
        return False
    tail_cut = window[-1].timestamp_ms - _TAIL_STILL_MS
    tail = [s for s in window if s.timestamp_ms >= tail_cut]
    body = [s for s in window if s.timestamp_ms < tail_cut]
    if not body or _ac_amplitude(tail) >= _AC_QUIET:
        return False
    moving = [s for s in body if abs(s.magnitude_g - 1.0) >= 0.3]
    if len(moving) < 2:
        return False
    duration_s = (moving[-1].timestamp_ms - moving[0].timestamp_ms) / 1000.0
    return duration_s >= _SOFT_COLLAPSE_MIN_S


def accel_signature(
    window: Sequence[AccelSample],
    thresholds: ThresholdsConfig,
) -> AccelSignature:
    """Classify a recent window of accelerometer samples."""
    if not window:
        return AccelSignature.UNKNOWN
    peak = _peak_magnitude(window)
    impact = peak >= thresholds.impact_g_threshold

    if not impact:
        if _is_soft_collapse(window, peak):
            return AccelSignature.SOFT_COLLAPSE
        return AccelSignature.QUIET

    # First impact in the window, not the latest peak: a later jolt must not
    # reset the tremor clock (seizure is rhythmic after the first hit).
    impact_idx = next(
        i for i, s in enumerate(window)
        if s.magnitude_g >= thresholds.impact_g_threshold
    )
    tail = window[impact_idx + 1:]
    if not tail:
        return AccelSignature.IMPACT_ONLY
    freq = _dominant_frequency_hz(tail)
    amp = _ac_amplitude(tail)
    tremor_lo, tremor_hi = thresholds.tremor_band_hz
    duration_s = (tail[-1].timestamp_ms - tail[0].timestamp_ms) / 1000.0
    if (freq is not None and tremor_lo <= freq <= tremor_hi
            and amp >= 0.2
            and duration_s >= thresholds.tremor_min_duration_s):
        return AccelSignature.IMPACT_TREMOR
    return AccelSignature.IMPACT_ONLY


# --------------------------------------------------------------------------- #
# Heart-rate signature
# --------------------------------------------------------------------------- #


class HrSignature(str, Enum):
    UNKNOWN = "unknown"
    RESTING = "resting"
    PANIC_SPIKE = "panic_spike"        # 100-130 BPM (PRD Scenario A)
    SEIZURE_SPIKE = "seizure_spike"    # >130 BPM (PRD Scenario B)
    BRADYCARDIA = "bradycardia"        # <50 BPM (PRD Scenario C)
    PULSE_LOST = "pulse_lost"          # cardiac arrest indicator


@dataclass
class HrAggregate:
    """Most-recent HR view used by :func:`hr_signature`."""

    latest_bpm: Optional[int]
    pulse_lost_s: float = 0.0          # contiguous time without a pulse sample


def hr_signature(agg: HrAggregate, thresholds: ThresholdsConfig) -> HrSignature:
    if agg.pulse_lost_s >= thresholds.pulse_loss_timeout_s:
        return HrSignature.PULSE_LOST
    bpm = agg.latest_bpm
    if bpm is None:
        return HrSignature.UNKNOWN
    if bpm < thresholds.hr_resting_low:
        return HrSignature.BRADYCARDIA
    if bpm >= thresholds.hr_seizure_low:
        return HrSignature.SEIZURE_SPIKE
    if bpm >= thresholds.hr_panic_low:
        return HrSignature.PANIC_SPIKE
    return HrSignature.RESTING


def aggregate_hr(
    samples: Sequence[SensorEvent],
    now_ms: int,
) -> HrAggregate:
    """Reduce a window of HR / pulse-loss events into an aggregate."""
    latest: Optional[HrSample] = None
    pulse_lost_total = 0.0
    for ev in samples:
        if isinstance(ev, HrSample):
            if latest is None or ev.timestamp_ms > latest.timestamp_ms:
                latest = ev
    for ev in samples:
        if isinstance(ev, PulseLost) and (latest is None or ev.timestamp_ms >= latest.timestamp_ms):
            pulse_lost_total += ev.duration_s
    if latest is None:
        return HrAggregate(latest_bpm=None, pulse_lost_s=pulse_lost_total)
    age_s = max(0.0, (now_ms - latest.timestamp_ms) / 1000.0)
    return HrAggregate(latest_bpm=latest.bpm, pulse_lost_s=max(pulse_lost_total, age_s))
