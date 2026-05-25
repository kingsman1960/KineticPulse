"""Pretrained pose backbone (YOLOv8n-pose, COCO 17 keypoints).

This module is independent of the trained fall classifier: it loads the
pretrained COCO pose model, which is what Pipeline 2 uses to drive
posture features and the temporal head.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from kineticpulse.config import PoseConfig
from kineticpulse.utils.logging import get_logger

log = get_logger(__name__)


# COCO-Pose keypoint indices.
KP_NOSE = 0
KP_LEFT_SHOULDER = 5
KP_RIGHT_SHOULDER = 6
KP_LEFT_HIP = 11
KP_RIGHT_HIP = 12
KP_LEFT_KNEE = 13
KP_RIGHT_KNEE = 14
KP_LEFT_ANKLE = 15
KP_RIGHT_ANKLE = 16


@dataclass
class PoseResult:
    """Pose result for a single person.

    ``keypoints`` shape: ``(17, 3)``, columns ``(x, y, conf)``.
    """

    keypoints: np.ndarray
    bbox_xyxy: Optional[np.ndarray]
    score: float
    timestamp_ms: int


class PoseEstimator:
    """Thin wrapper around the pretrained YOLOv8-pose model."""

    def __init__(self, cfg: PoseConfig) -> None:
        self.cfg = cfg
        self._model = None
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        if not self.cfg.enabled:
            log.info("PoseEstimator disabled by config.")
            return
        try:
            from ultralytics import YOLO
        except ImportError as e:
            raise ImportError(
                "ultralytics is required. Install with `pip install -r requirements.txt`."
            ) from e
        self._model = YOLO(self.cfg.weights)
        device = None if self.cfg.device in ("", "auto") else self.cfg.device
        if device is not None:
            try:
                self._model.to(device)
            except Exception as exc:
                log.warning("Could not move pose model to device %r: %s", device, exc)
        self._loaded = True
        log.info("PoseEstimator loaded: %s", self.cfg.weights)

    def infer(self, frame: np.ndarray, timestamp_ms: int) -> List[PoseResult]:
        if not self.cfg.enabled:
            return []
        if not self._loaded:
            self.load()
        results = self._model.predict(
            source=frame,
            imgsz=self.cfg.imgsz,
            conf=self.cfg.conf,
            verbose=False,
        )
        out: List[PoseResult] = []
        if not results:
            return out
        r0 = results[0]
        kpts = getattr(r0, "keypoints", None)
        boxes = getattr(r0, "boxes", None)
        if kpts is None or kpts.data is None:
            return out
        kp_arr = kpts.data.cpu().numpy() if hasattr(kpts.data, "cpu") else np.asarray(kpts.data)
        box_arr = None
        conf_arr = None
        if boxes is not None and boxes.xyxy is not None:
            box_arr = boxes.xyxy.cpu().numpy() if hasattr(boxes.xyxy, "cpu") else np.asarray(boxes.xyxy)
            conf_arr = boxes.conf.cpu().numpy() if hasattr(boxes.conf, "cpu") else np.asarray(boxes.conf)
        for i in range(kp_arr.shape[0]):
            out.append(PoseResult(
                keypoints=kp_arr[i],
                bbox_xyxy=box_arr[i] if box_arr is not None else None,
                score=float(conf_arr[i]) if conf_arr is not None else 1.0,
                timestamp_ms=timestamp_ms,
            ))
        return out

    @staticmethod
    def best_person(poses: List[PoseResult]) -> Optional[PoseResult]:
        if not poses:
            return None
        return max(poses, key=lambda p: p.score)
