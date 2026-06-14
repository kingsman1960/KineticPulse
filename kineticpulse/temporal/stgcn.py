"""Temporal action-recognition head.

Wraps a TSSTG (two-stream ST-GCN) classifier when its weights are
available, and degrades to a deterministic posture heuristic when
they are not. The public surface (``TemporalHead``, ``ActionLogits``,
``KeypointRingBuffer``) does not change with the backend, so the
fusion engine and tests stay decoupled from how the prediction is
made.

Backend selection happens lazily on the first ``maybe_predict()`` call
that has enough buffered frames:

* If ``temporal.weights`` (default ``models/tsstg/tsstg-model.pth``)
  exists and PyTorch is available, we load TSSTG and use it.
* Otherwise we log a single warning and fall back to a small
  heuristic over ``PoseFeatures``. This keeps unit tests, CI, and
  any deployment that has not yet downloaded the weights working.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, List, Optional

import numpy as np

from kineticpulse.config import TemporalConfig
from kineticpulse.utils.logging import get_logger
from kineticpulse.vision.features import PoseFeatures

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Public dataclasses
# --------------------------------------------------------------------------- #


@dataclass
class ActionLogits:
    """Per-class probabilities for the 4-class KineticPulse schema.

    The four fields sum to 1 (within float tolerance) when produced by
    either backend, so callers can treat them as a probability
    distribution. Extra context (e.g. raw 7-way TSSTG output) is
    intentionally not exposed here - downstream code consumes only the
    4-class collapse.
    """

    fallen: float
    falling: float
    stand: float
    sitting: float
    timestamp_ms: int

    @property
    def argmax_label(self) -> str:
        return max(
            ("fallen", "falling", "stand", "sitting"),
            key=lambda k: getattr(self, k),
        )


class KeypointRingBuffer:
    """Fixed-size circular buffer of pose keypoint arrays.

    Each entry is the per-person keypoint tensor for a single frame.
    For the YOLOv8n-pose pipeline this is shape ``(17, 3)`` (COCO-17,
    columns ``(x, y, score)``).
    """

    def __init__(self, maxlen: int) -> None:
        self.maxlen = int(maxlen)
        self._buf: Deque[np.ndarray] = collections.deque(maxlen=self.maxlen)

    def push(self, kpts: Optional[np.ndarray]) -> None:
        if kpts is not None:
            self._buf.append(kpts)

    def snapshot(self) -> List[np.ndarray]:
        return list(self._buf)

    def clear(self) -> None:
        self._buf.clear()

    def __len__(self) -> int:
        return len(self._buf)

    @property
    def is_full(self) -> bool:
        return len(self._buf) >= self.maxlen


# --------------------------------------------------------------------------- #
# Temporal head
# --------------------------------------------------------------------------- #


class TemporalHead:
    """Selects between a real TSSTG classifier and a heuristic fallback."""

    def __init__(self, cfg: TemporalConfig) -> None:
        self.cfg = cfg
        self._frame_idx = 0
        # Backend slots; populated lazily on first usable predict call.
        self._classifier = None
        self._classifier_loaded = False
        self._classifier_unavailable = False
        self._fallback_logged = False

    # ------------------------------------------------------------------ #
    # backend management
    # ------------------------------------------------------------------ #

    def _try_load_classifier(self) -> None:
        """Attempt to load TSSTG. Side-effects only; never raises."""
        if self._classifier_loaded or self._classifier_unavailable:
            return

        weights_path = Path(self.cfg.weights)
        if not weights_path.exists():
            self._classifier_unavailable = True
            log.warning(
                "TSSTG weights not found at %s - TemporalHead will use the "
                "heuristic fallback. Download tsstg-model.pth (see "
                "docs/MANUAL.md) to enable the real action classifier.",
                weights_path,
            )
            return

        try:
            from kineticpulse.temporal.tsstg import TsstgClassifier
        except ImportError as exc:
            self._classifier_unavailable = True
            log.warning(
                "Could not import TsstgClassifier (%s). Falling back to "
                "the heuristic.", exc,
            )
            return

        try:
            cls = TsstgClassifier(
                weights_path=weights_path,
                device=self.cfg.device,
                sequence_length=self.cfg.sequence_length,
            )
            cls.load()
        except Exception as exc:                          # noqa: BLE001
            self._classifier_unavailable = True
            log.warning(
                "Failed to initialise TSSTG (%s). Falling back to "
                "the heuristic.", exc,
            )
            return

        self._classifier = cls
        self._classifier_loaded = True
        log.info("TemporalHead is using the TSSTG action classifier.")

    # ------------------------------------------------------------------ #
    # prediction
    # ------------------------------------------------------------------ #

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

        self._try_load_classifier()
        if self._classifier is not None:
            result = self._predict_with_tsstg(keypoint_buffer, timestamp_ms)
            if result is not None:
                return result
            # If TSSTG inference failed mid-flight, fall through to
            # heuristic so the engine still receives a signal.
        return self._predict_with_heuristic(latest_features, timestamp_ms)

    # ------------------------------------------------------------------ #
    # backends
    # ------------------------------------------------------------------ #

    def _predict_with_tsstg(
        self,
        keypoint_buffer: KeypointRingBuffer,
        timestamp_ms: int,
    ) -> Optional[ActionLogits]:
        try:
            clip = keypoint_buffer.snapshot()
            pred = self._classifier.predict(
                clip,
                image_size=(self.cfg.image_width, self.cfg.image_height),
            )
        except Exception as exc:                          # noqa: BLE001
            if not self._fallback_logged:
                log.warning("TSSTG inference failed: %s. Using heuristic "
                            "for this frame.", exc)
                self._fallback_logged = True
            return None
        return ActionLogits(
            fallen=pred.fallen,
            falling=pred.falling,
            stand=pred.stand,
            sitting=pred.sitting,
            timestamp_ms=timestamp_ms,
        )

    @staticmethod
    def _predict_with_heuristic(
        latest_features: Optional[PoseFeatures],
        timestamp_ms: int,
    ) -> ActionLogits:
        """Posture-feature heuristic. Used when TSSTG is unavailable.

        Mirrors the original STUB behaviour but covers all four classes
        (the STUB was 3-class and pre-dated the sitting promotion).
        """
        angle = (latest_features.torso_angle_deg
                 if latest_features else None) or 0.0
        ar = (latest_features.aspect_ratio
              if latest_features else None) or 0.5
        vel = (latest_features.centroid_vel_pps
               if latest_features else None) or 0.0

        fallen_logit = 0.0
        falling_logit = 0.0
        stand_logit = 0.0
        sitting_logit = 0.0

        if angle > 60 or ar > 1.0:
            fallen_logit += 2.0
        if 30 < angle <= 60:
            falling_logit += 1.0
            sitting_logit += 0.5
        if vel > 300.0 and angle > 20:
            falling_logit += 1.5
        if angle < 30 and ar < 1.0:
            stand_logit += 2.0
        if 25 <= angle <= 50 and 0.7 <= ar <= 1.1 and vel < 200.0:
            sitting_logit += 1.5

        logits = np.array(
            [fallen_logit, falling_logit, stand_logit, sitting_logit],
            dtype=np.float32,
        )
        exp = np.exp(logits - logits.max())
        probs = exp / exp.sum()
        return ActionLogits(
            fallen=float(probs[0]),
            falling=float(probs[1]),
            stand=float(probs[2]),
            sitting=float(probs[3]),
            timestamp_ms=timestamp_ms,
        )


__all__ = ["ActionLogits", "KeypointRingBuffer", "TemporalHead"]
