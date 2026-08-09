"""Build WebRTC session meta (alert context + vitals) from a fusion snapshot."""

from __future__ import annotations

from typing import Any, Dict, Optional

from kineticpulse.fusion.engine import FusionSnapshot
from kineticpulse.webrtc.types import WebrtcSessionMeta


def build_session_meta(
    *,
    session_id: str,
    subject_id: str,
    location: str,
    snapshot: FusionSnapshot,
    extra: Optional[Dict[str, Any]] = None,
) -> WebrtcSessionMeta:
    d = snapshot.decision
    return WebrtcSessionMeta(
        session_id=session_id,
        timestamp_ms=snapshot.timestamp_ms,
        tier=d.tier.value,
        scenario=d.scenario,
        subject_id=subject_id,
        location=location,
        reason=d.reason,
        detector_class=snapshot.detector_class,
        action_class=snapshot.action_class,
        action_confidence=snapshot.action_conf,
        heart_rate_bpm=snapshot.latest_hr_bpm,
        hr_signature=snapshot.hr.value,
        accel_magnitude_g=snapshot.latest_accel_g,
        accel_signature=snapshot.accel.value,
        extra=dict(extra or {}),
    )
