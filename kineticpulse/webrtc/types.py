"""Typed payloads used by the WebRTC signaling protocol."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class IceServerConfig:
    urls: List[str]
    username: Optional[str] = None
    credential: Optional[str] = None

    def as_rtc_kwargs(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"urls": self.urls}
        if self.username:
            out["username"] = self.username
        if self.credential:
            out["credential"] = self.credential
        return out


@dataclass
class WebrtcSessionMeta:
    session_id: str
    timestamp_ms: int
    tier: str
    scenario: str
    subject_id: str
    location: str
    reason: str
    detector_class: Optional[str] = None
    action_class: Optional[str] = None
    action_confidence: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

