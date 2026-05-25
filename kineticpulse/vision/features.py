"""Pose feature extraction.

Pure-math helpers that turn a sequence of pose keypoints into the
geometric features used by the rule-based fusion engine:

- Torso angle (deg) - 0 = upright, 90 = horizontal.
- Bounding-box aspect ratio (width / height) - tall person -> < 1, lying -> > 1.
- Centroid vertical velocity (pixels / second).
- Keypoint stillness (variance over the last N samples).

All functions accept ``None`` keypoints gracefully so callers can wire
them up without runtime defensiveness.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from kineticpulse.vision.pose import (
    KP_LEFT_HIP,
    KP_LEFT_SHOULDER,
    KP_RIGHT_HIP,
    KP_RIGHT_SHOULDER,
    PoseResult,
)


@dataclass
class PoseFeatures:
    """Per-frame pose features used by the fusion engine."""

    torso_angle_deg: Optional[float]    # 0 = upright, 90 = horizontal
    aspect_ratio: Optional[float]       # bbox w / h; None if bbox missing
    centroid_vel_pps: Optional[float]   # signed: positive = falling downward
    stillness: Optional[float]          # 0 = motion; large = still
    timestamp_ms: int


def _mid(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return (a + b) / 2.0


def _conf_ok(kpt: np.ndarray, threshold: float = 0.3) -> bool:
    return kpt.shape[-1] >= 3 and float(kpt[..., 2]) >= threshold


def torso_angle_deg(keypoints: Optional[np.ndarray], conf_threshold: float = 0.3) -> Optional[float]:
    """Angle between the torso vector (hips -> shoulders) and the vertical axis.

    Returns degrees in ``[0, 90]`` where ``0`` is upright and ``90`` is
    horizontal. Returns ``None`` when key landmarks are missing or low-conf.
    """
    if keypoints is None or keypoints.shape[0] < 17:
        return None
    ls, rs = keypoints[KP_LEFT_SHOULDER], keypoints[KP_RIGHT_SHOULDER]
    lh, rh = keypoints[KP_LEFT_HIP], keypoints[KP_RIGHT_HIP]
    if not (_conf_ok(ls, conf_threshold) and _conf_ok(rs, conf_threshold)
            and _conf_ok(lh, conf_threshold) and _conf_ok(rh, conf_threshold)):
        return None
    shoulder_mid = _mid(ls[:2], rs[:2])
    hip_mid = _mid(lh[:2], rh[:2])
    dx = shoulder_mid[0] - hip_mid[0]
    dy = hip_mid[1] - shoulder_mid[1]   # image y increases downward; flip for vertical
    if dx == 0 and dy == 0:
        return None
    angle_from_vertical = math.degrees(math.atan2(abs(dx), abs(dy)))
    return float(max(0.0, min(90.0, angle_from_vertical)))


def aspect_ratio(bbox_xyxy: Optional[Sequence[float]]) -> Optional[float]:
    """Width-to-height ratio of a bbox. ``None`` if bbox is missing or zero-height."""
    if bbox_xyxy is None or len(bbox_xyxy) < 4:
        return None
    x1, y1, x2, y2 = bbox_xyxy[:4]
    w, h = float(x2 - x1), float(y2 - y1)
    if h <= 0:
        return None
    return w / h


def centroid_velocity(
    prev_centroid: Optional[Sequence[float]],
    curr_centroid: Optional[Sequence[float]],
    dt_ms: float,
) -> Optional[float]:
    """Vertical velocity in pixels/second.

    Positive means the subject is moving downward in image space (which is
    what we want to detect as "falling").
    """
    if prev_centroid is None or curr_centroid is None or dt_ms <= 0:
        return None
    dy_px = float(curr_centroid[1] - prev_centroid[1])
    return dy_px * (1000.0 / dt_ms)


def keypoint_stillness(history: Sequence[np.ndarray], conf_threshold: float = 0.3) -> Optional[float]:
    """Inverse of motion: low value means moving, high value means still.

    Implemented as ``1 / (1 + mean_std)`` where ``mean_std`` is the average
    standard deviation across all sufficiently-confident keypoints over the
    history window. Returns ``None`` when the window is too short.
    """
    if not history or len(history) < 3:
        return None
    stacked = np.stack(history, axis=0)            # (T, K, 3)
    if stacked.shape[-1] >= 3:
        confs = stacked[..., 2]                    # (T, K)
        good_mask = (confs.mean(axis=0) >= conf_threshold)
        if not good_mask.any():
            return None
        coords = stacked[..., :2][:, good_mask]    # (T, K_good, 2)
    else:
        coords = stacked[..., :2]
    std = coords.std(axis=0)                       # (K_good, 2)
    mean_std = float(std.mean())
    return float(1.0 / (1.0 + mean_std))


def extract_features(
    pose: Optional[PoseResult],
    prev_pose: Optional[PoseResult],
    history: Sequence[np.ndarray],
    timestamp_ms: int,
) -> PoseFeatures:
    """Bundle the per-frame features used by the fusion engine."""
    if pose is None:
        return PoseFeatures(
            torso_angle_deg=None,
            aspect_ratio=None,
            centroid_vel_pps=None,
            stillness=None,
            timestamp_ms=timestamp_ms,
        )

    angle = torso_angle_deg(pose.keypoints)
    ar = aspect_ratio(pose.bbox_xyxy) if pose.bbox_xyxy is not None else None

    vel = None
    if prev_pose is not None and pose.bbox_xyxy is not None and prev_pose.bbox_xyxy is not None:
        prev_cx = (prev_pose.bbox_xyxy[0] + prev_pose.bbox_xyxy[2]) / 2.0
        prev_cy = (prev_pose.bbox_xyxy[1] + prev_pose.bbox_xyxy[3]) / 2.0
        curr_cx = (pose.bbox_xyxy[0] + pose.bbox_xyxy[2]) / 2.0
        curr_cy = (pose.bbox_xyxy[1] + pose.bbox_xyxy[3]) / 2.0
        dt_ms = pose.timestamp_ms - prev_pose.timestamp_ms
        vel = centroid_velocity((prev_cx, prev_cy), (curr_cx, curr_cy), dt_ms)

    still = keypoint_stillness(history)

    return PoseFeatures(
        torso_angle_deg=angle,
        aspect_ratio=ar,
        centroid_vel_pps=vel,
        stillness=still,
        timestamp_ms=timestamp_ms,
    )
