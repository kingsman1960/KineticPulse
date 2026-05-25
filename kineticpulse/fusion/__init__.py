"""Sensor fusion engine implementing PRD section 5 (tier classification)."""

from kineticpulse.fusion.rules import (
    AccelSignature,
    HrSignature,
    PoseSignature,
    accel_signature,
    hr_signature,
    pose_signature,
)
from kineticpulse.fusion.tiers import EmergencyTier, TierDecision, classify
from kineticpulse.fusion.engine import FusionEngine, FusionSnapshot

__all__ = [
    "AccelSignature",
    "HrSignature",
    "PoseSignature",
    "accel_signature",
    "hr_signature",
    "pose_signature",
    "EmergencyTier",
    "TierDecision",
    "classify",
    "FusionEngine",
    "FusionSnapshot",
]
