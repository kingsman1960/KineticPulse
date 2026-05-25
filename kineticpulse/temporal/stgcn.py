"""ST-GCN temporal action-recognition head (STUB).

Once we have a temporal-keypoint dataset of falls (annotated clips, not
single frames), this module will host a real ST-GCN implementation that
classifies the last ~2 s of pose keypoints into action probabilities.

The merged dataset for the initial release is detection-only, so we
ship a deterministic pass-through stub that:

- Accepts the same inputs / produces the same outputs as the planned model.
- Reports a confidence proportional to a simple posture heuristic.
- Lets the rest of the pipeline run end-to-end today.

When the real model lands, only this file changes - the engine and
config interfaces stay the same.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass
from typing import Deque, List, Optional

import numpy as np

from kineticpulse.config import TemporalConfig
from kineticpulse.utils.logging import get_logger
from kineticpulse.vision.features import PoseFeatures

log = get_logger(__name__)


@dataclass
class ActionLogits:
    """Probabilities for the same labels the YOLO detector uses."""

    fallen: float
    falling: float
    stand: float
    timestamp_ms: int

    @property
    def argmax_label(self) -> str:
        return max(("fallen", "falling", "stand"), key=lambda k: getattr(self, k))


class KeypointRingBuffer:
    """Fixed-size circular buffer of pose keypoint arrays."""

    def __init__(self, maxlen: int) -> None:
        self.maxlen = maxlen
        self._buf: Deque[np.ndarray] = collections.deque(maxlen=maxlen)

    def push(self, kpts: Optional[np.ndarray]) -> None:
        if kpts is not None:
            self._buf.append(kpts)

    def snapshot(self) -> List[np.ndarray]:
        return list(self._buf)

    def __len__(self) -> int:
        return len(self._buf)

    @property
    def is_full(self) -> bool:
        return len(self._buf) >= self.maxlen


class TemporalHead:
    """Pass-through ST-GCN stub. See module docstring."""

    def __init__(self, cfg: TemporalConfig) -> None:
        self.cfg = cfg
        self._frame_idx = 0

    def maybe_predict(
        self,
        keypoint_buffer: KeypointRingBuffer,
        latest_features: Optional[PoseFeatures],
        timestamp_ms: int,
    ) -> Optional[ActionLogits]:
        """Run prediction every ``cfg.stride`` frames once the buffer has filled."""
        self._frame_idx += 1
        if not self.cfg.enabled:
            return None
        if not keypoint_buffer.is_full:
            return None
        if self._frame_idx % max(1, self.cfg.stride) != 0:
            return None

        # Stub heuristic: torso angle + aspect ratio -> rough class probs.
        angle = (latest_features.torso_angle_deg if latest_features else None) or 0.0
        ar = (latest_features.aspect_ratio if latest_features else None) or 0.5
        vel = (latest_features.centroid_vel_pps if latest_features else None) or 0.0

        fallen_logit = 0.0
        falling_logit = 0.0
        stand_logit = 0.0
        if angle > 60 or ar > 1.0:
            fallen_logit += 2.0
        if 30 < angle <= 60:
            falling_logit += 1.0
        if vel > 300.0 and angle > 20:
            falling_logit += 1.5
        if angle < 30 and ar < 1.0:
            stand_logit += 2.0

        logits = np.array([fallen_logit, falling_logit, stand_logit], dtype=np.float32)
        exp = np.exp(logits - logits.max())
        probs = exp / exp.sum()
        return ActionLogits(
            fallen=float(probs[0]),
            falling=float(probs[1]),
            stand=float(probs[2]),
            timestamp_ms=timestamp_ms,
        )
