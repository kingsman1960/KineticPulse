"""Temporal action-recognition head (ST-GCN stub).

See :mod:`kineticpulse.temporal.stgcn` for the current pass-through
implementation and the planned real model.
"""

from kineticpulse.temporal.stgcn import (
    ActionLogits,
    KeypointRingBuffer,
    TemporalHead,
)

__all__ = ["ActionLogits", "KeypointRingBuffer", "TemporalHead"]
