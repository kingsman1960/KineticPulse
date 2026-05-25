"""KineticPulse fall-posture detector.

Loads the YOLOv8 model trained by ``scripts/train.py`` and runs inference
on a frame to produce :class:`Detection` objects. Supports ``.pt`` weights
via Ultralytics; ``.onnx`` and ``.engine`` are also accepted because
Ultralytics' :class:`~ultralytics.YOLO` loads both transparently.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from kineticpulse.config import DetectorConfig
from kineticpulse.utils.logging import get_logger

log = get_logger(__name__)


class PostureClass(str, Enum):
    """The 3-class unified schema produced by the merge script."""

    FALLEN = "fallen"
    FALLING = "falling"
    STAND = "stand"

    @classmethod
    def from_index(cls, idx: int) -> "PostureClass":
        return [cls.FALLEN, cls.FALLING, cls.STAND][idx]


@dataclass
class Detection:
    """A single fall-posture detection inside a frame."""

    bbox_xyxy: Tuple[float, float, float, float]   # absolute pixel coordinates
    cls: PostureClass
    confidence: float
    timestamp_ms: int

    @property
    def width(self) -> float:
        return self.bbox_xyxy[2] - self.bbox_xyxy[0]

    @property
    def height(self) -> float:
        return self.bbox_xyxy[3] - self.bbox_xyxy[1]

    @property
    def aspect_ratio(self) -> float:
        h = self.height
        return (self.width / h) if h > 0 else 0.0

    @property
    def centroid(self) -> Tuple[float, float]:
        x1, y1, x2, y2 = self.bbox_xyxy
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


class FallDetector:
    """Wraps an Ultralytics YOLO model and exposes a clean per-frame API."""

    def __init__(self, cfg: DetectorConfig) -> None:
        self.cfg = cfg
        self._model = None
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        weights = Path(self.cfg.weights)
        if not weights.exists():
            raise FileNotFoundError(
                f"Detector weights not found: {weights}. "
                f"Train one with `python scripts/train.py` first."
            )
        try:
            from ultralytics import YOLO
        except ImportError as e:
            raise ImportError(
                "ultralytics is required. Install with `pip install -r requirements.txt`."
            ) from e
        self._model = YOLO(str(weights))
        device = None if self.cfg.device in ("", "auto") else self.cfg.device
        if device is not None:
            try:
                self._model.to(device)
            except Exception as exc:
                log.warning("Could not move model to device %r: %s", device, exc)
        self._loaded = True
        log.info("FallDetector loaded: %s", weights)

    def infer(self, frame: np.ndarray, timestamp_ms: int) -> List[Detection]:
        if not self._loaded:
            self.load()
        results = self._model.predict(
            source=frame,
            imgsz=self.cfg.imgsz,
            conf=self.cfg.conf,
            iou=self.cfg.iou,
            verbose=False,
        )
        detections: List[Detection] = []
        if not results:
            return detections
        r0 = results[0]
        boxes = getattr(r0, "boxes", None)
        if boxes is None or boxes.xyxy is None:
            return detections
        xyxy = boxes.xyxy.cpu().numpy() if hasattr(boxes.xyxy, "cpu") else np.asarray(boxes.xyxy)
        cls_arr = boxes.cls.cpu().numpy() if hasattr(boxes.cls, "cpu") else np.asarray(boxes.cls)
        conf_arr = boxes.conf.cpu().numpy() if hasattr(boxes.conf, "cpu") else np.asarray(boxes.conf)
        for i in range(xyxy.shape[0]):
            try:
                cls = PostureClass.from_index(int(cls_arr[i]))
            except IndexError:
                continue
            x1, y1, x2, y2 = xyxy[i].tolist()
            detections.append(Detection(
                bbox_xyxy=(float(x1), float(y1), float(x2), float(y2)),
                cls=cls,
                confidence=float(conf_arr[i]),
                timestamp_ms=timestamp_ms,
            ))
        return detections

    @staticmethod
    def best_person(detections: List[Detection]) -> Optional[Detection]:
        """Pick the most confident detection. KineticPulse tracks a single subject."""
        if not detections:
            return None
        return max(detections, key=lambda d: d.confidence)
