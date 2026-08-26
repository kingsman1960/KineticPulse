"""Shared caregiver-facing runtime status for monitoring + session meta.

Updated by the dispatch worker; read by ``MonitoringPublisher``.
"""

from __future__ import annotations

import collections
import time
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional


@dataclass
class CaregiverRuntimeStatus:
    voice_status: str = "not_required"
    alert_dispatch_status: str = "idle"
    _events: Deque[Dict] = field(default_factory=lambda: collections.deque(maxlen=40))
    _event_seq: int = 0

    def set_voice(self, status: str) -> None:
        self.voice_status = status

    def set_alert(self, status: str) -> None:
        self.alert_dispatch_status = status

    def push_event(
        self,
        *,
        severity: str,
        category: str,
        title: str,
        detail: str,
        timestamp_ms: Optional[int] = None,
    ) -> None:
        self._event_seq += 1
        # Runtime callers pass fusion's monotonic timestamps. Those are valid
        # for internal ordering but not for dashboard dates or SQLite history.
        if timestamp_ms is None or timestamp_ms < 1_000_000_000_000:
            timestamp_ms = int(time.time() * 1000)
        self._events.append(
            {
                "id": f"runtime-{self._event_seq}",
                "timestamp_ms": timestamp_ms,
                "severity": severity,
                "category": category,
                "title": title,
                "detail": detail,
            }
        )

    def events_payload(self) -> List[Dict]:
        return list(reversed(self._events))
