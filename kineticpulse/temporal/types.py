"""Lightweight, dependency-free types shared across the pipeline.

Kept in its own module so that ``kineticpulse.fusion.rules`` (and the
fusion-engine tests) can consume :class:`ActionLogits` without pulling
in NumPy, PyTorch, or the heavy ``kineticpulse.temporal.stgcn`` import
graph.

The dataclass intentionally has zero non-stdlib dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ActionLogits:
    """Per-class probabilities for the 4-class KineticPulse schema.

    The four numeric fields sum to 1 (within float tolerance) for both
    the TSSTG backend and the heuristic fallback, so callers can treat
    them as a probability distribution.

    ``stable_label`` is the hysteresis-confirmed argmax (i.e. the label
    that has held for at least ``temporal.hysteresis_min_consecutive``
    predictions in a row). It is ``None`` until the head has settled,
    which lets downstream consumers distinguish "we are still warming
    up" from "we are confident". Use it in preference to
    :attr:`argmax_label` whenever you need a low-jitter signal — e.g.
    when feeding the fusion engine.
    """

    fallen: float
    falling: float
    stand: float
    sitting: float
    timestamp_ms: int
    stable_label: Optional[str] = None

    @property
    def argmax_label(self) -> str:
        """Raw (per-frame) argmax across the four KineticPulse classes."""
        return max(
            ("fallen", "falling", "stand", "sitting"),
            key=lambda k: getattr(self, k),
        )

    def confidence_of(self, label: str) -> float:
        """Probability assigned to ``label`` (0.0 if unknown class name)."""
        return float(getattr(self, label, 0.0))


__all__ = ["ActionLogits"]
