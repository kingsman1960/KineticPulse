"""Unit tests for the temporal action-classifier subsystem.

Covers:

* :mod:`kineticpulse.temporal.graph` - coco_cut layout and adjacency
  partitioning (uniform / distance / spatial).
* :mod:`kineticpulse.temporal.keypoint_adapter` - COCO-17 -> coco_cut
  14-joint conversion, including the synthetic neck.
* :mod:`kineticpulse.temporal.stgcn_model` - end-to-end forward shape
  on the two-stream model with random inputs.
* :mod:`kineticpulse.temporal.stgcn` - ``ActionLogits`` schema and
  ``TemporalHead`` fallback behaviour when TSSTG weights are missing.

The model-forward test is gated on ``torch`` being importable so the
suite still runs in environments that only need the post-processor and
fusion logic.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from kineticpulse.config import TemporalConfig
from kineticpulse.temporal.graph import (
    COCO_CUT_NEIGHBOR_LINK,
    COCO_CUT_NUM_NODES,
    Graph,
)
from kineticpulse.temporal.keypoint_adapter import (
    LEFT_SHOULDER_IDX,
    RIGHT_SHOULDER_IDX,
    coco17_to_coco_cut_14,
)
from kineticpulse.temporal.stgcn import (
    ActionLogits,
    KeypointRingBuffer,
    TemporalHead,
)


# --------------------------------------------------------------------------- #
# Graph
# --------------------------------------------------------------------------- #


def test_coco_cut_graph_has_14_nodes_and_neck_at_13():
    g = Graph(layout="coco_cut", strategy="spatial")
    assert g.num_node == 14
    assert g.center == 13
    # Every published edge involves nodes < 14.
    for u, v in COCO_CUT_NEIGHBOR_LINK:
        assert 0 <= u < COCO_CUT_NUM_NODES
        assert 0 <= v < COCO_CUT_NUM_NODES


def test_spatial_strategy_yields_three_partitions():
    g = Graph(layout="coco_cut", strategy="spatial", max_hop=1)
    # Spatial partitioning emits hop=0 -> 1 matrix, hop>=1 -> 2 matrices.
    assert g.A.shape == (3, COCO_CUT_NUM_NODES, COCO_CUT_NUM_NODES)


def test_uniform_and_distance_strategies_have_expected_partition_counts():
    g_uniform = Graph(layout="coco_cut", strategy="uniform", max_hop=1)
    assert g_uniform.A.shape == (1, COCO_CUT_NUM_NODES, COCO_CUT_NUM_NODES)

    g_distance = Graph(layout="coco_cut", strategy="distance", max_hop=1)
    assert g_distance.A.shape == (2, COCO_CUT_NUM_NODES, COCO_CUT_NUM_NODES)


def test_unsupported_layout_or_strategy_raises():
    with pytest.raises(ValueError):
        Graph(layout="halpe", strategy="spatial")
    with pytest.raises(ValueError):
        Graph(layout="coco_cut", strategy="weird")


# --------------------------------------------------------------------------- #
# Keypoint adapter
# --------------------------------------------------------------------------- #


def test_adapter_single_frame_drops_face_keypoints_and_appends_neck():
    # Synthesise a frame where every joint has a unique x so we can
    # verify exactly which COCO indices survive.
    kpts = np.zeros((17, 3), dtype=np.float32)
    for i in range(17):
        kpts[i] = (i * 10.0, i * 10.0 + 1.0, 0.9)

    out = coco17_to_coco_cut_14(kpts)
    assert out.shape == (14, 3)
    # Index 0 is nose, kept verbatim.
    assert out[0, 0] == pytest.approx(0.0)
    # Index 1 is COCO 5 = left_shoulder (x=50).
    assert out[LEFT_SHOULDER_IDX, 0] == pytest.approx(50.0)
    # Index 2 is COCO 6 = right_shoulder (x=60).
    assert out[RIGHT_SHOULDER_IDX, 0] == pytest.approx(60.0)
    # Index 13 is the neck = midpoint of shoulders (= 55).
    assert out[13, 0] == pytest.approx(55.0)
    assert out[13, 1] == pytest.approx(56.0)


def test_adapter_clip_preserves_temporal_axis():
    T = 5
    clip = np.tile(
        np.arange(17, dtype=np.float32).reshape(17, 1), (1, 3),
    )                                                    # (17, 3)
    clip = np.repeat(clip[None, :, :], T, axis=0)         # (T, 17, 3)
    out = coco17_to_coco_cut_14(clip)
    assert out.shape == (T, 14, 3)


def test_adapter_rejects_wrong_keypoint_count():
    bad = np.zeros((13, 3), dtype=np.float32)
    with pytest.raises(ValueError):
        coco17_to_coco_cut_14(bad)


# --------------------------------------------------------------------------- #
# Two-stream model forward shape
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    pytest.importorskip("torch", reason="torch not installed") is None,
    reason="torch not installed",
)
def test_two_stream_forward_produces_sigmoid_probabilities():
    import torch

    from kineticpulse.temporal.stgcn_model import TwoStreamSpatialTemporalGraph

    model = TwoStreamSpatialTemporalGraph(
        graph_args={"strategy": "spatial", "layout": "coco_cut"},
        num_class=7,
    ).eval()

    N, T, V = 2, 30, 14
    pts = torch.randn(N, 3, T, V)
    mot = torch.randn(N, 2, T - 1, V)

    with torch.no_grad():
        out = model((pts, mot))

    assert out.shape == (N, 7)
    # Sigmoid output -> every entry in (0, 1).
    assert ((out >= 0) & (out <= 1)).all().item()


# --------------------------------------------------------------------------- #
# ActionLogits + TemporalHead
# --------------------------------------------------------------------------- #


def test_action_logits_argmax_includes_sitting():
    al = ActionLogits(fallen=0.10, falling=0.05, stand=0.20, sitting=0.65,
                      timestamp_ms=123)
    assert al.argmax_label == "sitting"


def test_keypoint_ring_buffer_capacity_and_fullness():
    rb = KeypointRingBuffer(maxlen=3)
    assert not rb.is_full
    for i in range(5):
        rb.push(np.full((17, 3), i, dtype=np.float32))
    assert len(rb) == 3
    assert rb.is_full
    snap = rb.snapshot()
    assert snap[0][0, 0] == 2.0     # oldest retained
    assert snap[-1][0, 0] == 4.0    # newest


def test_temporal_head_falls_back_when_weights_missing(tmp_path: Path):
    """No weights -> the head must use the heuristic and still produce a
    well-formed ActionLogits whose probabilities sum to 1."""
    cfg = TemporalConfig(
        enabled=True,
        window_size=10,
        stride=1,
        weights=str(tmp_path / "does-not-exist.pth"),
    )
    head = TemporalHead(cfg)
    rb = KeypointRingBuffer(maxlen=cfg.window_size)
    for _ in range(cfg.window_size):
        rb.push(np.zeros((17, 3), dtype=np.float32))

    logits = head.maybe_predict(rb, latest_features=None, timestamp_ms=42)
    assert isinstance(logits, ActionLogits)
    total = logits.fallen + logits.falling + logits.stand + logits.sitting
    assert total == pytest.approx(1.0, abs=1e-5)
    # Heuristic should have logged a single warning and recorded the
    # classifier as unavailable so we don't keep retrying I/O.
    assert head._classifier is None
    assert head._classifier_unavailable is True


def test_temporal_head_disabled_returns_none(tmp_path: Path):
    cfg = TemporalConfig(enabled=False, weights=str(tmp_path / "missing.pth"))
    head = TemporalHead(cfg)
    rb = KeypointRingBuffer(maxlen=cfg.window_size)
    for _ in range(cfg.window_size):
        rb.push(np.zeros((17, 3), dtype=np.float32))
    assert head.maybe_predict(rb, None, timestamp_ms=0) is None
