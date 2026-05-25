"""Unit tests for pose feature math (no model dependencies)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from kineticpulse.vision.features import (
    aspect_ratio,
    centroid_velocity,
    keypoint_stillness,
    torso_angle_deg,
)


def _make_keypoints(shoulder_mid_y: float, hip_mid_y: float,
                    shoulder_dx: float = 0.0, hip_dx: float = 0.0,
                    conf: float = 0.9) -> np.ndarray:
    """Build a (17, 3) keypoint array with shoulders + hips populated."""
    kpts = np.zeros((17, 3), dtype=np.float32)
    kpts[5] = [320.0 - 50.0 + shoulder_dx, shoulder_mid_y, conf]   # L shoulder
    kpts[6] = [320.0 + 50.0 + shoulder_dx, shoulder_mid_y, conf]   # R shoulder
    kpts[11] = [320.0 - 50.0 + hip_dx, hip_mid_y, conf]            # L hip
    kpts[12] = [320.0 + 50.0 + hip_dx, hip_mid_y, conf]            # R hip
    return kpts


# --- torso_angle_deg ---------------------------------------------------- #


def test_torso_angle_upright_is_near_zero() -> None:
    kpts = _make_keypoints(shoulder_mid_y=100.0, hip_mid_y=300.0)
    assert torso_angle_deg(kpts) == pytest.approx(0.0, abs=1e-3)


def test_torso_angle_horizontal_is_near_ninety() -> None:
    # shoulders and hips at the same y but offset horizontally -> torso is flat
    kpts = _make_keypoints(shoulder_mid_y=200.0, hip_mid_y=200.0,
                           shoulder_dx=-150.0, hip_dx=150.0)
    angle = torso_angle_deg(kpts)
    assert angle is not None and angle > 80.0


def test_torso_angle_low_confidence_returns_none() -> None:
    kpts = _make_keypoints(shoulder_mid_y=100.0, hip_mid_y=300.0, conf=0.1)
    assert torso_angle_deg(kpts) is None


def test_torso_angle_diagonal_45() -> None:
    kpts = _make_keypoints(shoulder_mid_y=100.0, hip_mid_y=200.0,
                           shoulder_dx=-100.0, hip_dx=0.0)
    angle = torso_angle_deg(kpts)
    assert angle is not None
    assert 40.0 <= angle <= 50.0


# --- aspect_ratio ------------------------------------------------------- #


def test_aspect_ratio_tall_subject_below_one() -> None:
    assert aspect_ratio((0.0, 0.0, 100.0, 300.0)) == pytest.approx(1 / 3, rel=1e-3)


def test_aspect_ratio_lying_subject_above_one() -> None:
    assert aspect_ratio((0.0, 0.0, 300.0, 100.0)) == pytest.approx(3.0, rel=1e-3)


def test_aspect_ratio_handles_zero_height() -> None:
    assert aspect_ratio((0.0, 100.0, 100.0, 100.0)) is None


def test_aspect_ratio_handles_none() -> None:
    assert aspect_ratio(None) is None


# --- centroid_velocity -------------------------------------------------- #


def test_centroid_velocity_downward_is_positive() -> None:
    vel = centroid_velocity((100.0, 200.0), (100.0, 350.0), dt_ms=500.0)
    assert vel is not None and vel > 0.0
    assert vel == pytest.approx(300.0, rel=1e-3)


def test_centroid_velocity_upward_is_negative() -> None:
    vel = centroid_velocity((100.0, 350.0), (100.0, 200.0), dt_ms=500.0)
    assert vel is not None and vel < 0.0


def test_centroid_velocity_zero_dt_returns_none() -> None:
    assert centroid_velocity((0.0, 0.0), (0.0, 100.0), dt_ms=0.0) is None


# --- keypoint_stillness ------------------------------------------------- #


def test_stillness_high_for_still_window() -> None:
    history = [_make_keypoints(100.0, 300.0) for _ in range(10)]
    val = keypoint_stillness(history)
    assert val is not None and val > 0.9   # essentially 1.0


def test_stillness_low_for_moving_window() -> None:
    history = [_make_keypoints(100.0 + i * 20.0, 300.0 + i * 20.0) for i in range(10)]
    val = keypoint_stillness(history)
    assert val is not None and val < 0.2


def test_stillness_returns_none_for_short_window() -> None:
    history = [_make_keypoints(100.0, 300.0)]
    assert keypoint_stillness(history) is None
