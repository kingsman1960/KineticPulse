"""Time-sync utilities for multi-modal alignment (PRD section 4).

All modalities (frames, IMU samples, HR samples, STT events) carry a
``timestamp_ms`` measured against the same monotonic clock so the fusion
engine can window them together.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


def now_ms() -> int:
    """Monotonic milliseconds since process start; safe for cross-modality diffs."""
    return int(time.monotonic() * 1000.0)


@dataclass
class MonotonicClock:
    """Tiny wrapper to make the clock injectable for tests."""

    _start_ns: int = 0

    def __post_init__(self) -> None:
        self._start_ns = time.monotonic_ns()

    def now_ms(self) -> int:
        return int((time.monotonic_ns() - self._start_ns) / 1_000_000)

    def now_s(self) -> float:
        return (time.monotonic_ns() - self._start_ns) / 1_000_000_000.0
