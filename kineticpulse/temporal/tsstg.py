"""TSSTG action classifier loader and inference wrapper.

Wraps the released ``tsstg-model.pth`` checkpoint
(GajuuzZ/Human-Falling-Detect-Tracks) so the rest of KineticPulse can
ask "given the last ~30 frames of pose keypoints, what action is this
person doing?" and get a 4-class probability over our schema.

The model itself outputs sigmoid probabilities for 7 actions:

    Standing, Walking, Sitting, Lying Down, Stand up, Sit down, Fall Down

We collapse these to KineticPulse's 4-class schema:

    fallen   <- Lying Down
    falling  <- Fall Down
    stand    <- max(Standing, Walking, Stand up)
    sitting  <- max(Sitting, Sit down)

The 4 numbers are then renormalised to sum to 1 so downstream
consumers (fusion engine, OSD, alerts) can treat them as a probability
distribution.

Why ``max`` rather than sum for the multi-label heads? The released
checkpoint was trained with sigmoid + BCE, so the 7 outputs are not
mutually exclusive. Summing inflates ``stand`` / ``sitting`` whenever
two transition classes co-fire, while ``max`` faithfully reports the
most confident sub-class. Empirically this matches what GajuuzZ's
demo does ("argmax over 7 classes").
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Tuple

import numpy as np

from kineticpulse.temporal.keypoint_adapter import coco17_to_coco_cut_14
from kineticpulse.utils.logging import get_logger

log = get_logger(__name__)

# Order here must match the released checkpoint's class index order.
TSSTG_CLASS_NAMES: Tuple[str, ...] = (
    "Standing", "Walking", "Sitting", "Lying Down",
    "Stand up", "Sit down", "Fall Down",
)


# --------------------------------------------------------------------------- #
# Pre-processing helpers (kept numpy-only for testability without torch).
# --------------------------------------------------------------------------- #


def _normalize_points_with_size(xy: np.ndarray,
                                width: int,
                                height: int) -> np.ndarray:
    """Scale pixel coordinates into the ``[0, 1]`` range."""
    out = xy.astype(np.float32, copy=True)
    out[..., 0] = out[..., 0] / float(width)
    out[..., 1] = out[..., 1] / float(height)
    return out


def _scale_pose(xy: np.ndarray) -> np.ndarray:
    """Per-frame min-max rescale to ``[-1, 1]`` per axis.

    Mirrors :func:`pose_utils.scale_pose` from the upstream project.
    """
    if xy.ndim == 2:
        was_single = True
        clip = xy[np.newaxis]
    else:
        was_single = False
        clip = xy.astype(np.float32, copy=True)

    out = clip.astype(np.float32, copy=True)
    for i in range(out.shape[0]):
        xy_min = np.nanmin(out[i], axis=0)
        xy_max = np.nanmax(out[i], axis=0)
        denom = xy_max - xy_min
        # Guard against degenerate frames (all joints identical).
        denom = np.where(denom == 0, 1.0, denom)
        out[i] = ((out[i] - xy_min) / denom) * 2.0 - 1.0
    return out[0] if was_single else out


# --------------------------------------------------------------------------- #
# Result dataclass
# --------------------------------------------------------------------------- #


@dataclass
class TsstgPrediction:
    """4-class collapsed prediction plus the raw 7-way sigmoid output."""

    raw_probs: np.ndarray                       # shape (7,), float32
    fallen: float
    falling: float
    stand: float
    sitting: float

    @property
    def argmax_label(self) -> str:
        return max(("fallen", "falling", "stand", "sitting"),
                   key=lambda k: getattr(self, k))


# --------------------------------------------------------------------------- #
# Inference wrapper
# --------------------------------------------------------------------------- #


class TsstgClassifier:
    """Lazy-loaded inference wrapper around the TSSTG checkpoint."""

    def __init__(self,
                 weights_path: Path,
                 device: str = "auto",
                 sequence_length: int = 30) -> None:
        self.weights_path = Path(weights_path)
        self.device_str = device
        self.sequence_length = int(sequence_length)
        self._model = None
        self._device = None
        self._loaded = False

    @property
    def is_available(self) -> bool:
        return self.weights_path.exists()

    # ------------------------------------------------------------------ #
    # loading
    # ------------------------------------------------------------------ #

    def load(self) -> None:
        if self._loaded:
            return
        if not self.is_available:
            raise FileNotFoundError(
                f"TSSTG weights not found at {self.weights_path}. "
                f"Download tsstg-model.pth (see docs/MANUAL.md) and place "
                f"it at this path, or override `temporal.weights` in your "
                f"runtime config."
            )

        try:
            import torch
        except ImportError as exc:
            raise ImportError("PyTorch is required for TsstgClassifier") from exc

        # Local import: keeps `import kineticpulse.temporal.tsstg` from
        # pulling torch into environments that only need the dataclass.
        from kineticpulse.temporal.stgcn_model import (
            TwoStreamSpatialTemporalGraph,
        )

        if self.device_str in ("auto", ""):
            self._device = torch.device(
                "cuda" if torch.cuda.is_available() else "cpu"
            )
        else:
            self._device = torch.device(self.device_str)

        self._model = TwoStreamSpatialTemporalGraph(
            graph_args={"strategy": "spatial", "layout": "coco_cut"},
            num_class=len(TSSTG_CLASS_NAMES),
        ).to(self._device)

        # ``weights_only=False`` because the checkpoint was saved long
        # before the PyTorch 2.4+ pickle-safety default. The file is
        # vendored from a known-good URL, so this is acceptable.
        state = torch.load(
            str(self.weights_path),
            map_location=self._device,
            weights_only=False,
        )
        self._model.load_state_dict(state)
        self._model.eval()
        self._loaded = True
        log.info("TsstgClassifier loaded: %s on %s",
                 self.weights_path, self._device)

    # ------------------------------------------------------------------ #
    # inference
    # ------------------------------------------------------------------ #

    def predict(self,
                keypoint_sequence: Sequence[np.ndarray],
                image_size: Tuple[int, int]) -> TsstgPrediction:
        """Classify a clip of pose keypoints.

        Parameters
        ----------
        keypoint_sequence
            Iterable of ``(17, 3)`` COCO-17 keypoint arrays - one per
            frame, ordered from oldest to newest. The clip is right-
            aligned to ``self.sequence_length`` (older frames truncated,
            short clips padded with the last frame).
        image_size
            ``(width, height)`` of the source frames in pixels, used
            to normalise coordinates into ``[0, 1]`` before the
            per-clip rescale.
        """
        import torch  # local import: see load()

        if not self._loaded:
            self.load()

        if len(keypoint_sequence) < 2:
            raise ValueError(
                "Need at least 2 frames to compute the motion stream"
            )

        clip = np.stack(keypoint_sequence, axis=0).astype(np.float32)  # (T, 17, 3)
        if clip.shape[1:] != (17, 3):
            raise ValueError(
                f"Expected each frame to have shape (17, 3), got "
                f"{clip.shape[1:]}"
            )

        T_target = self.sequence_length
        if clip.shape[0] > T_target:
            clip = clip[-T_target:]
        elif clip.shape[0] < T_target:
            pad = np.repeat(clip[-1:], T_target - clip.shape[0], axis=0)
            clip = np.concatenate([clip, pad], axis=0)

        pts = coco17_to_coco_cut_14(clip)                              # (T, 14, 3)

        width, height = int(image_size[0]), int(image_size[1])
        pts[..., :2] = _normalize_points_with_size(pts[..., :2], width, height)
        pts[..., :2] = _scale_pose(pts[..., :2])

        # (T, V, C) -> (1, C, T, V)
        pts_t = torch.from_numpy(pts).float().permute(2, 0, 1).unsqueeze(0)
        # Motion: temporal diff of (x, y) only -> (1, 2, T-1, V)
        mot = pts_t[:, :2, 1:, :] - pts_t[:, :2, :-1, :]

        pts_t = pts_t.to(self._device)
        mot = mot.to(self._device)

        with torch.no_grad():
            out = self._model((pts_t, mot)).squeeze(0).cpu().numpy()   # (7,)

        # 7-class -> 4-class collapse.
        standing, walking, sitting_p, lying_down, stand_up, sit_down, fall_down = out
        fallen = float(lying_down)
        falling = float(fall_down)
        stand = float(max(standing, walking, stand_up))
        sitting = float(max(sitting_p, sit_down))

        total = fallen + falling + stand + sitting
        if total > 0.0:
            inv = 1.0 / total
            fallen *= inv
            falling *= inv
            stand *= inv
            sitting *= inv

        return TsstgPrediction(
            raw_probs=out.astype(np.float32),
            fallen=fallen,
            falling=falling,
            stand=stand,
            sitting=sitting,
        )


__all__ = [
    "TsstgClassifier",
    "TsstgPrediction",
    "TSSTG_CLASS_NAMES",
]
