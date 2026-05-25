"""Emergency tier classification per PRD section 5.

Inputs are the signature enums produced by :mod:`rules`. Output is one of
four tiers that the engine uses to decide whether to dismiss, verify
verbally, or escalate immediately.

Tier mapping (verbatim from the PRD):

- Tier 0  : Dismissal. CV anomaly without supporting impact / vitals.
- Tier 1  : Standard fall. Trigger voice verification.
- Tier 2A : Suspected seizure. Bypass voice, alert immediately.
- Tier 2B : Syncope / cardiac event. Bypass voice, alert immediately.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from kineticpulse.fusion.rules import (
    AccelSignature,
    HrSignature,
    PoseSignature,
)


class EmergencyTier(str, Enum):
    NONE = "none"
    TIER_0_DISMISS = "tier_0_dismiss"
    TIER_1_VERIFY = "tier_1_verify"
    TIER_2_SEIZURE = "tier_2_seizure"
    TIER_2_CARDIAC = "tier_2_cardiac"

    @property
    def bypasses_voice(self) -> bool:
        return self in (EmergencyTier.TIER_2_SEIZURE, EmergencyTier.TIER_2_CARDIAC)


@dataclass
class TierDecision:
    tier: EmergencyTier
    scenario: str       # human-readable: "A", "B", "C", "D", or "monitoring"
    reason: str


def classify(
    pose: PoseSignature,
    accel: AccelSignature,
    hr: HrSignature,
) -> TierDecision:
    """Map a (pose, accel, hr) triple to a tier decision."""

    # --- Scenario C: syncope / cardiac arrest --------------------------- #
    if hr == HrSignature.PULSE_LOST:
        return TierDecision(
            tier=EmergencyTier.TIER_2_CARDIAC,
            scenario="C",
            reason="Pulse signal lost; suspected cardiac arrest.",
        )
    if hr == HrSignature.BRADYCARDIA and pose in (PoseSignature.PRONE, PoseSignature.FALLING):
        return TierDecision(
            tier=EmergencyTier.TIER_2_CARDIAC,
            scenario="C",
            reason="Severe bradycardia coincident with posture collapse.",
        )
    if accel == AccelSignature.SOFT_COLLAPSE and hr in (HrSignature.BRADYCARDIA, HrSignature.PULSE_LOST):
        return TierDecision(
            tier=EmergencyTier.TIER_2_CARDIAC,
            scenario="C",
            reason="Soft collapse with bradycardia / pulse loss.",
        )

    # --- Scenario B: suspected seizure ---------------------------------- #
    if accel == AccelSignature.IMPACT_TREMOR and hr == HrSignature.SEIZURE_SPIKE:
        return TierDecision(
            tier=EmergencyTier.TIER_2_SEIZURE,
            scenario="B",
            reason="Impact + rhythmic tremor + extreme HR spike (>130 BPM).",
        )
    if (pose == PoseSignature.PRONE
            and accel == AccelSignature.IMPACT_TREMOR
            and hr in (HrSignature.PANIC_SPIKE, HrSignature.SEIZURE_SPIKE)):
        return TierDecision(
            tier=EmergencyTier.TIER_2_SEIZURE,
            scenario="B",
            reason="Prone subject with sustained tremor and elevated HR.",
        )

    # --- Scenario D: false positive ------------------------------------- #
    if (pose in (PoseSignature.UPRIGHT, PoseSignature.FALSE_POSITIVE, PoseSignature.UNKNOWN)
            and accel in (AccelSignature.QUIET, AccelSignature.UNKNOWN)
            and hr in (HrSignature.RESTING, HrSignature.UNKNOWN)):
        return TierDecision(
            tier=EmergencyTier.TIER_0_DISMISS,
            scenario="D",
            reason="No impact and stable vitals; CV anomaly dismissed.",
        )

    # --- Scenario A: standard fall -------------------------------------- #
    if (pose in (PoseSignature.FALLING, PoseSignature.PRONE)
            and accel in (AccelSignature.IMPACT_ONLY, AccelSignature.IMPACT_TREMOR,
                          AccelSignature.SOFT_COLLAPSE)):
        return TierDecision(
            tier=EmergencyTier.TIER_1_VERIFY,
            scenario="A",
            reason="Posture change + impact detected; verifying verbally.",
        )
    if pose in (PoseSignature.FALLING, PoseSignature.PRONE):
        return TierDecision(
            tier=EmergencyTier.TIER_1_VERIFY,
            scenario="A",
            reason="Fall-like posture without impact; verifying verbally.",
        )
    if accel in (AccelSignature.IMPACT_ONLY, AccelSignature.IMPACT_TREMOR) and hr != HrSignature.RESTING:
        return TierDecision(
            tier=EmergencyTier.TIER_1_VERIFY,
            scenario="A",
            reason="Impact spike with elevated HR; verifying verbally.",
        )

    return TierDecision(
        tier=EmergencyTier.NONE,
        scenario="monitoring",
        reason="No fall signatures detected.",
    )
