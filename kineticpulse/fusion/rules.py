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
    """
    cls = (detector_class or "").lower()
    if cls == "fallen":
        if (torso_angle_deg is not None and torso_angle_deg < 30
                and (aspect_ratio is None or aspect_ratio < 1.0)):
            return PoseSignature.UPRIGHT
        return PoseSignature.PRONE
    if cls == "falling":
        return PoseSignature.FALLING
    if cls == "stand":
        if (centroid_vel_pps is not None and centroid_vel_pps > 400.0
                and torso_angle_deg is not None and torso_angle_deg > 45):
            return PoseSignature.FALLING
        if (torso_angle_deg is not None and torso_angle_deg > 70
                and aspect_ratio is not None and aspect_ratio > 1.0):
            return PoseSignature.PRONE
        return PoseSignature.UPRIGHT
    if cls == "sitting":
        # Sudden seated drop with marked tilt - possible syncope.
        if (centroid_vel_pps is not None and centroid_vel_pps > 350.0
                and torso_angle_deg is not None and torso_angle_deg > 50):
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
        if _ac_amplitude(window) < 0.15:
            return AccelSignature.QUIET
        if _peak_magnitude(window) >= 1.8:    # soft impact (~2g) without crossing threshold
            return AccelSignature.SOFT_COLLAPSE
        return AccelSignature.QUIET

    impact_idx = max(range(len(window)), key=lambda i: window[i].magnitude_g)
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
        elif isinstance(ev, PulseLost):
            pulse_lost_total += ev.duration_s
    if latest is None:
        return HrAggregate(latest_bpm=None, pulse_lost_s=pulse_lost_total)
    age_s = max(0.0, (now_ms - latest.timestamp_ms) / 1000.0)
    return HrAggregate(latest_bpm=latest.bpm, pulse_lost_s=max(pulse_lost_total, age_s))
