"""Posture-aware post-processing for the YOLOv8 detector.

Why this module exists
======================

The 4-class detector ships strong ``stand`` and ``fallen`` heads but the
``sitting`` head is dragged down by label noise in the training set
(documented in ``dataset/README.md``). At inference time we routinely see
the *raw* per-class scores look like::

    fallen=0.59  falling=0.20  stand=0.11  sitting=0.62   <- user is sitting

Both ``sitting`` (0.62) and ``fallen`` (0.59) co-fire with ``stand`` low.
A single ``argmax`` is brittle here:

* On one frame ``sitting`` wins (0.62 > 0.59) and we report sitting.
* On the next frame ``fallen`` wins (0.64 > 0.57) and we report a *false*
  fallen - dangerous, because the rest of the pipeline could escalate it.

This module groups raw detections that overlap in space (IoU >=
``iou_group_threshold``) and applies safety-aware priority rules so
that a noisy 4-way tie collapses to the *correct* class instead of
flickering.

Pipeline
--------

1. Caller runs ``model.predict(conf=very-low, iou=very-high)`` so the
   per-class boxes survive NMS.
2. Caller passes ``boxes (N,4) xyxy``, ``cls_ids (N,)``, ``confs (N,)``
   into :func:`reweight_postures`.
3. We greedy-group boxes by spatial overlap, take the per-class max
   score inside each group, then apply :func:`choose_class`.
4. One :class:`PosturePrediction` per group is returned, ready to be
   converted into a :class:`~kineticpulse.vision.detector.Detection`.

Tuning
------

Default thresholds were tuned on 64 seconds of UGREEN webcam recording
(see ``runs/camera_check/`` for the raw debug log) so that:

* The user-as-sitting frames at t=16:11:40-45 collapse to ``sitting``
  (previously oscillated between sitting and fallen).
* Genuine fall transitions (``falling``: 0.77, ``fallen``: 0.37) are
  kept as ``falling`` for safety.
* Frames where the user sits stiffly upright still legitimately report
  ``stand`` because the sitting head is too quiet (sit < 0.10) - those
  cases need a data-side fix, not a post-processing fix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Tunable thresholds. Centralised here so unit tests + live_predict.py +
# the FallDetector all stay in lockstep.
# ---------------------------------------------------------------------------

# Class indices match PostureClass.from_index() in detector.py.
IDX_FALLEN = 0
IDX_FALLING = 1
IDX_STAND = 2
IDX_SITTING = 3

DEFAULT_IOU_GROUP = 0.5
"""Boxes whose IoU exceeds this are treated as the same physical subject."""

DEFAULT_OUTPUT_MIN_CONF = 0.40
"""Predictions with chosen confidence below this are dropped."""


@dataclass
class PriorityConfig:
    """All knobs in one place."""

    iou_group: float = DEFAULT_IOU_GROUP
    output_min_conf: float = DEFAULT_OUTPUT_MIN_CONF

    # ``falling`` is safety-critical: bias towards reporting it as long
    # as it is meaningfully active and not dwarfed by something else.
    falling_min: float = 0.40
    falling_vs_others_margin: float = 0.10  # falling >= max(others) - margin

    # ``fallen`` is also safety-critical, but we must avoid mistaking
    # an upright sitting subject for a fallen one. Require ``fallen`` to
    # beat ``sitting`` by a clear margin.
    fallen_min: float = 0.45
    fallen_vs_sitting_margin: float = 0.10  # fallen > sitting + margin

    # ``sitting`` is *under*-confident in the trained model; rescue it
    # whenever it is plausibly active and not crushed by stand.
    sitting_min: float = 0.35
    sitting_vs_stand_bias: float = 0.15  # sitting >= stand - bias


@dataclass
class PosturePrediction:
    """Output of :func:`reweight_postures` - one entry per spatial group."""

    bbox_xyxy: Tuple[float, float, float, float]
    cls_idx: int
    confidence: float
    raw_scores: Dict[int, float] = field(default_factory=dict)
    rule_fired: str = "argmax"


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _iou_xyxy(a: np.ndarray, b: np.ndarray) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _group_by_iou(boxes: np.ndarray, iou_thresh: float) -> List[List[int]]:
    """Greedy spatial clustering. Largest box is the group seed; smaller
    boxes whose IoU with the seed >= ``iou_thresh`` are absorbed.

    This is the same shape of operation as standard NMS but
    *class-agnostic*, which is exactly what we need to recombine the
    per-class duplicates produced by ``model.predict(conf=0.01,
    iou=0.95)``.
    """
    n = len(boxes)
    if n == 0:
        return []
    # Sort by area, largest first - the largest box of a group is the
    # least likely to be a per-class fragment.
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    order = np.argsort(-areas).tolist()

    groups: List[List[int]] = []
    visited = [False] * n
    for i in order:
        if visited[i]:
            continue
        visited[i] = True
        members = [i]
        for j in order:
            if visited[j] or i == j:
                continue
            if _iou_xyxy(boxes[i], boxes[j]) >= iou_thresh:
                visited[j] = True
                members.append(j)
        groups.append(members)
    return groups


# ---------------------------------------------------------------------------
# The actual rule engine
# ---------------------------------------------------------------------------


def choose_class(per_class_max: Dict[int, float],
                 cfg: PriorityConfig) -> Tuple[int, float, str]:
    """Apply the safety-aware priority rules.

    Returns ``(class_idx, confidence, rule_name)``.
    ``rule_name`` is one of ``falling-rescue`` / ``fallen-rescue`` /
    ``sitting-rescue`` / ``argmax`` so callers (and unit tests) can see
    which branch fired.
    """
    fln = per_class_max.get(IDX_FALLEN, 0.0)
    fall = per_class_max.get(IDX_FALLING, 0.0)
    sta = per_class_max.get(IDX_STAND, 0.0)
    sit = per_class_max.get(IDX_SITTING, 0.0)

    others_for_falling = max(fln, sta, sit)
    if (fall >= cfg.falling_min
            and fall >= others_for_falling - cfg.falling_vs_others_margin):
        return IDX_FALLING, fall, "falling-rescue"

    if (fln >= cfg.fallen_min
            and fln > sit + cfg.fallen_vs_sitting_margin
            and fln > sta):
        return IDX_FALLEN, fln, "fallen-rescue"

    if (sit >= cfg.sitting_min
            and sit >= sta - cfg.sitting_vs_stand_bias):
        return IDX_SITTING, sit, "sitting-rescue"

    best_idx = max(per_class_max, key=lambda k: per_class_max[k])
    return best_idx, per_class_max[best_idx], "argmax"


def reweight_postures(boxes: np.ndarray,
                      cls_ids: np.ndarray,
                      confs: np.ndarray,
                      cfg: PriorityConfig | None = None
                      ) -> List[PosturePrediction]:
    """Group raw per-class boxes spatially and apply priority rules.

    Parameters
    ----------
    boxes : (N, 4) float ndarray
        xyxy in absolute pixel coordinates.
    cls_ids : (N,) int ndarray
        Predicted class index per box (must be in ``{0,1,2,3}``).
    confs : (N,) float ndarray
        Per-box confidence (Ultralytics' max-class score).
    cfg : PriorityConfig | None
        Optional override of thresholds.

    Returns
    -------
    list of PosturePrediction
        One entry per spatial group, with the *re-weighted* class.
        Predictions whose chosen confidence falls below
        ``cfg.output_min_conf`` are silently dropped.
    """
    cfg = cfg or PriorityConfig()
    boxes = np.asarray(boxes, dtype=np.float32).reshape(-1, 4)
    cls_ids = np.asarray(cls_ids, dtype=np.int32).reshape(-1)
    confs = np.asarray(confs, dtype=np.float32).reshape(-1)
    if len(boxes) == 0:
        return []

    groups = _group_by_iou(boxes, cfg.iou_group)
    out: List[PosturePrediction] = []
    for members in groups:
        per_class: Dict[int, float] = {
            IDX_FALLEN: 0.0, IDX_FALLING: 0.0,
            IDX_STAND: 0.0, IDX_SITTING: 0.0,
        }
        best_box_idx = members[0]
        best_box_conf = -1.0
        for idx in members:
            c = int(cls_ids[idx])
            cf = float(confs[idx])
            if c in per_class and cf > per_class[c]:
                per_class[c] = cf
            if cf > best_box_conf:
                best_box_conf = cf
                best_box_idx = idx

        chosen_idx, chosen_conf, rule = choose_class(per_class, cfg)
        if chosen_conf < cfg.output_min_conf:
            continue

        x1, y1, x2, y2 = boxes[best_box_idx].tolist()
        out.append(PosturePrediction(
            bbox_xyxy=(float(x1), float(y1), float(x2), float(y2)),
            cls_idx=chosen_idx,
            confidence=float(chosen_conf),
            raw_scores=dict(per_class),
            rule_fired=rule,
        ))
    return out


__all__ = [
    "PriorityConfig",
    "PosturePrediction",
    "choose_class",
    "reweight_postures",
    "IDX_FALLEN",
    "IDX_FALLING",
    "IDX_STAND",
    "IDX_SITTING",
    "DEFAULT_IOU_GROUP",
    "DEFAULT_OUTPUT_MIN_CONF",
]
