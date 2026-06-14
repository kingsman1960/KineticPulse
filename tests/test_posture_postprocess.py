"""Regression tests for the posture priority post-processor.

The thresholds in :mod:`kineticpulse.vision.posture_postprocess` were
tuned on a 64-second UGREEN webcam recording where the four raw class
heads produce specific co-firing patterns. These tests pin down the
key frames so future tuning does not silently regress the user-facing
behaviour:

* a clearly-sitting frame ends up as ``sitting`` (not ``fallen``)
* a clearly-falling frame ends up as ``falling`` (safety-critical)
* an upright stand frame stays ``stand``
* an ambiguous sit/stand tie goes to ``sitting`` (the symptom that
  triggered the post-processor in the first place)
"""

from __future__ import annotations

import numpy as np
import pytest

from kineticpulse.vision.posture_postprocess import (
    IDX_FALLEN,
    IDX_FALLING,
    IDX_SITTING,
    IDX_STAND,
    PriorityConfig,
    choose_class,
    reweight_postures,
)


def _scores(fallen=0.0, falling=0.0, stand=0.0, sitting=0.0):
    return {
        IDX_FALLEN: fallen,
        IDX_FALLING: falling,
        IDX_STAND: stand,
        IDX_SITTING: sitting,
    }


def test_sitting_rescue_when_fallen_co_fires():
    # Real frame at t=16:11:42 in the UGREEN diagnostic log: user is
    # sitting but the fallen head co-fires almost as strongly. Argmax
    # would say "fallen" - the rules must say "sitting".
    cls, conf, rule = choose_class(
        _scores(fallen=0.64, falling=0.0, stand=0.08, sitting=0.57),
        PriorityConfig(),
    )
    assert cls == IDX_SITTING
    assert rule == "sitting-rescue"
    assert conf == 0.57


def test_falling_takes_priority_for_safety():
    # t=16:11:09: a transition frame. We bias towards reporting falling
    # so the fusion engine can react.
    cls, _, rule = choose_class(
        _scores(fallen=0.37, falling=0.77, stand=0.22, sitting=0.07),
        PriorityConfig(),
    )
    assert cls == IDX_FALLING
    assert rule == "falling-rescue"


def test_stand_remains_when_only_stand_is_active():
    # Quiet stand frame; nothing else is loud enough to win a rescue.
    cls, _, rule = choose_class(
        _scores(fallen=0.02, falling=0.03, stand=0.66, sitting=0.08),
        PriorityConfig(),
    )
    assert cls == IDX_STAND
    assert rule == "argmax"


def test_ambiguous_sit_vs_stand_goes_to_sitting():
    # The classic "user is on a chair, model says stand" frame.
    # sitting raw is well above the rescue floor and within the bias
    # window of stand, so we re-attribute to sitting.
    cls, _, rule = choose_class(
        _scores(fallen=0.04, falling=0.37, stand=0.59, sitting=0.46),
        PriorityConfig(),
    )
    assert cls == IDX_SITTING
    assert rule == "sitting-rescue"


def test_genuine_fallen_still_wins_when_clearly_apart_from_sitting():
    # If the subject is really on the floor the fallen head should
    # outrun sitting by a large margin.
    cls, _, rule = choose_class(
        _scores(fallen=0.85, falling=0.10, stand=0.10, sitting=0.05),
        PriorityConfig(),
    )
    assert cls == IDX_FALLEN
    assert rule == "fallen-rescue"


def test_reweight_groups_overlapping_per_class_boxes():
    # Same physical subject, four near-identical boxes - one per class -
    # as we get back from model.predict(conf=0.01, iou=0.95).
    boxes = np.array([
        [100, 200, 300, 600],
        [101, 199, 299, 601],
        [102, 198, 301, 599],
        [99, 201, 302, 602],
    ], dtype=np.float32)
    cls_ids = np.array([IDX_FALLEN, IDX_FALLING, IDX_STAND, IDX_SITTING],
                       dtype=np.int32)
    confs = np.array([0.59, 0.20, 0.11, 0.62], dtype=np.float32)

    preds = reweight_postures(boxes, cls_ids, confs, PriorityConfig())

    assert len(preds) == 1, "All four overlapping boxes should collapse to one"
    pred = preds[0]
    assert pred.cls_idx == IDX_SITTING
    assert pred.rule_fired == "sitting-rescue"
    # float32 round-trip; the per-class max must round-trip the raw conf.
    assert pred.raw_scores[IDX_SITTING] == pytest.approx(0.62, abs=1e-5)
    assert pred.raw_scores[IDX_FALLEN] == pytest.approx(0.59, abs=1e-5)


def test_reweight_keeps_separate_subjects_separate():
    # Two non-overlapping subjects in the same frame - no grouping.
    boxes = np.array([
        [100, 200, 300, 600],   # subject A
        [800, 200, 1000, 600],  # subject B (no overlap)
    ], dtype=np.float32)
    cls_ids = np.array([IDX_STAND, IDX_FALLEN], dtype=np.int32)
    confs = np.array([0.80, 0.70], dtype=np.float32)

    preds = reweight_postures(boxes, cls_ids, confs, PriorityConfig())
    assert len(preds) == 2
    classes = sorted(p.cls_idx for p in preds)
    assert classes == sorted([IDX_STAND, IDX_FALLEN])


def test_low_confidence_predictions_are_dropped():
    # Even if rules pick something, predictions below output_min_conf
    # should be filtered out so the OSD stays clean.
    boxes = np.array([[100, 100, 200, 200]], dtype=np.float32)
    cls_ids = np.array([IDX_STAND], dtype=np.int32)
    confs = np.array([0.10], dtype=np.float32)
    preds = reweight_postures(boxes, cls_ids, confs,
                              PriorityConfig(output_min_conf=0.4))
    assert preds == []


def test_empty_input_returns_empty():
    preds = reweight_postures(
        np.zeros((0, 4), dtype=np.float32),
        np.zeros((0,), dtype=np.int32),
        np.zeros((0,), dtype=np.float32),
        PriorityConfig(),
    )
    assert preds == []
