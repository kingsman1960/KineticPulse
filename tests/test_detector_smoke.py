"""Smoke test for the trained YOLOv8 detector + Pipeline 2 adapter.

Loads the 4-class checkpoint produced by ``scripts/train.py`` (default
location ``runs/detect/kp_v2_4cls/weights/best.pt``) and runs inference
on a single test image, then asserts the adapter in
:mod:`kineticpulse.vision.detector` returns well-formed
:class:`Detection` objects with the unified :class:`PostureClass` enum.

The whole module is skipped when either the trained weights or the
merged dataset is not on disk - that keeps CI green on fresh clones
where the user has not run training/merge yet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WEIGHTS = REPO_ROOT / "runs" / "detect" / "kp_v2_4cls" / "weights" / "best.pt"
TEST_IMAGES_DIR = REPO_ROOT / "dataset" / "_merged" / "test" / "images"


def _have_artifacts() -> bool:
    if not DEFAULT_WEIGHTS.exists():
        return False
    if not TEST_IMAGES_DIR.exists():
        return False
    return any(TEST_IMAGES_DIR.iterdir())


pytestmark = pytest.mark.skipif(
    not _have_artifacts(),
    reason=(
        "Detector smoke test needs trained weights at "
        f"{DEFAULT_WEIGHTS} and a merged dataset under {TEST_IMAGES_DIR}. "
        "Run `python scripts/merge_datasets.py` and `python scripts/train.py` "
        "to produce them."
    ),
)


def _import_or_skip(module: str):
    pytest.importorskip(module, reason=f"{module} not installed; skipping detector smoke test.")


def _first_test_image() -> Path:
    for entry in sorted(TEST_IMAGES_DIR.iterdir()):
        if entry.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            return entry
    pytest.skip(f"No JPG/PNG images found in {TEST_IMAGES_DIR}.")


def test_falldetector_loads_and_infers_on_test_image() -> None:
    _import_or_skip("cv2")
    _import_or_skip("ultralytics")
    import cv2

    from kineticpulse.config import DetectorConfig
    from kineticpulse.vision.detector import (
        Detection,
        FallDetector,
        PostureClass,
    )

    image_path = _first_test_image()
    frame = cv2.imread(str(image_path))
    assert frame is not None, f"OpenCV failed to read {image_path}"

    detector = FallDetector(
        DetectorConfig(
            weights=str(DEFAULT_WEIGHTS),
            conf=0.25,
            iou=0.45,
            imgsz=640,
            device="cpu",   # CPU keeps the test portable across CI runners
        )
    )
    detector.load()

    detections = detector.infer(frame, timestamp_ms=0)
    assert isinstance(detections, list)
    assert all(isinstance(d, Detection) for d in detections)

    if not detections:
        pytest.skip(
            f"Detector returned no boxes on {image_path.name}; that is allowed "
            "(some test images are empty/edge cases) but offers no signal for "
            "the smoke check."
        )

    best = FallDetector.best_person(detections)
    assert best is not None
    assert isinstance(best.cls, PostureClass)
    assert best.cls in {
        PostureClass.FALLEN,
        PostureClass.FALLING,
        PostureClass.STAND,
        PostureClass.SITTING,
    }
    assert 0.0 < best.confidence <= 1.0
    x1, y1, x2, y2 = best.bbox_xyxy
    assert x2 > x1 and y2 > y1, f"Degenerate bbox: {best.bbox_xyxy}"
    assert best.timestamp_ms == 0
