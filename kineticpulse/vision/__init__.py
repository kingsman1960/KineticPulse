"""Vision stage: capture, fall detector, pose, and feature extraction."""

from kineticpulse.vision.capture import (
    Frame,
    FrameQueue,
    FrameSource,
    UsbWebcam,
    CsiCamera,
    RtspStream,
    FileSource,
    build_source,
)
from kineticpulse.vision.detector import Detection, FallDetector, PostureClass
from kineticpulse.vision.features import (
    PoseFeatures,
    aspect_ratio,
    centroid_velocity,
    extract_features,
    keypoint_stillness,
    torso_angle_deg,
)
from kineticpulse.vision.pose import PoseEstimator, PoseResult

__all__ = [
    "Frame",
    "FrameQueue",
    "FrameSource",
    "UsbWebcam",
    "CsiCamera",
    "RtspStream",
    "FileSource",
    "build_source",
    "Detection",
    "FallDetector",
    "PostureClass",
    "PoseEstimator",
    "PoseResult",
    "PoseFeatures",
    "aspect_ratio",
    "centroid_velocity",
    "extract_features",
    "keypoint_stillness",
    "torso_angle_deg",
]
