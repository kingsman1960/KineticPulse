"""Keypoint format adapter: COCO-17 (YOLOv8-pose) -> coco_cut 14 (TSSTG).

The TSSTG checkpoint expects 14 joints in a specific order (see
:mod:`kineticpulse.temporal.graph`). YOLOv8n-pose produces 17 joints
in standard COCO order. This module re-indexes COCO-17 down to 13
body joints and appends a synthetic ``neck`` joint at the shoulder
midpoint, giving the 14-joint tensor the model wants.
"""

from __future__ import annotations

import numpy as np


# COCO-17 indices (left/right ears + eyes are dropped; keep nose +
# shoulders/elbows/wrists/hips/knees/ankles).
COCO17_KEEP_INDICES: np.ndarray = np.array(
    [0, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16],
    dtype=np.int32,
)

# Position of the left and right shoulder *after* re-indexing. Used to
# synthesise the neck joint.
LEFT_SHOULDER_IDX = 1
RIGHT_SHOULDER_IDX = 2


def coco17_to_coco_cut_14(keypoints: np.ndarray) -> np.ndarray:
    """Convert COCO-17 keypoints to the TSSTG ``coco_cut`` 14-joint format.

    Parameters
    ----------
    keypoints : np.ndarray
        Either ``(17, C)`` for a single frame or ``(T, 17, C)`` for a
        clip. ``C`` must be 2 (x, y) or 3 (x, y, score). The input is
        not modified in place.

    Returns
    -------
    np.ndarray
        Shape ``(14, C)`` or ``(T, 14, C)`` with the same dtype as the
        input.
    """
    if keypoints.ndim == 2:
        was_single = True
        kpts = keypoints[np.newaxis]
    elif keypoints.ndim == 3:
        was_single = False
        kpts = keypoints
    else:
        raise ValueError(
            f"Expected 2D or 3D array, got shape {keypoints.shape}"
        )

    if kpts.shape[1] != 17:
        raise ValueError(
            f"Expected 17 COCO joints in axis 1, got {kpts.shape[1]}"
        )
    if kpts.shape[2] not in (2, 3):
        raise ValueError(
            f"Expected channels of size 2 or 3, got {kpts.shape[2]}"
        )

    cut13 = kpts[:, COCO17_KEEP_INDICES, :]
    neck = (cut13[:, LEFT_SHOULDER_IDX, :]
            + cut13[:, RIGHT_SHOULDER_IDX, :]) / 2.0
    cut14 = np.concatenate([cut13, neck[:, np.newaxis, :]], axis=1)
    return cut14[0] if was_single else cut14


__all__ = [
    "coco17_to_coco_cut_14",
    "COCO17_KEEP_INDICES",
    "LEFT_SHOULDER_IDX",
    "RIGHT_SHOULDER_IDX",
]
