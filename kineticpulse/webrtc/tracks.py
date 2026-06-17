"""Media tracks for aiortc WebRTC publishing."""

from __future__ import annotations

import asyncio
import time
from fractions import Fraction
from typing import Optional

from kineticpulse.config import CameraConfig
from kineticpulse.utils.logging import get_logger

log = get_logger(__name__)


class CameraVideoTrack:
    """aiortc.VideoStreamTrack backed by OpenCV capture.

    Kept as a lightweight wrapper so importing this module does not require
    aiortc unless the track is actually instantiated.
    """

    kind = "video"

    def __init__(self, camera_cfg: CameraConfig):
        try:
            import cv2
            from aiortc import VideoStreamTrack
            from av import VideoFrame
        except ImportError as exc:
            raise ImportError(
                "aiortc/av/opencv-python are required for CameraVideoTrack."
            ) from exc

        self._cv2 = cv2
        self._VideoStreamTrack = VideoStreamTrack
        self._VideoFrame = VideoFrame
        self._track = VideoStreamTrack()
        self._camera_cfg = camera_cfg
        self._cap = None
        self._start_t = time.time()
        self._frame_counter = 0
        self._lock = asyncio.Lock()

    async def recv(self):
        """Proxy method compatible with aiortc custom track API."""
        if self._cap is None:
            self._open_capture()
        async with self._lock:
            ok, frame = self._cap.read()
            if not ok or frame is None:
                await asyncio.sleep(0.03)
                ok, frame = self._cap.read()
                if not ok or frame is None:
                    raise RuntimeError("Camera read failed for WebRTC track.")
            vf = self._VideoFrame.from_ndarray(frame, format="bgr24")
            self._frame_counter += 1
            fps = max(1, int(self._camera_cfg.fps))
            vf.pts = self._frame_counter
            vf.time_base = Fraction(1, fps)
            return vf

    def stop(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def _open_capture(self) -> None:
        device_str = str(self._camera_cfg.device)
        device = int(device_str) if device_str.isdigit() else device_str
        cap = self._cv2.VideoCapture(device, self._cv2.CAP_ANY)
        if not cap.isOpened():
            raise RuntimeError(f"Could not open camera for WebRTC: {device_str}")
        if self._camera_cfg.width > 0:
            cap.set(self._cv2.CAP_PROP_FRAME_WIDTH, self._camera_cfg.width)
        if self._camera_cfg.height > 0:
            cap.set(self._cv2.CAP_PROP_FRAME_HEIGHT, self._camera_cfg.height)
        if self._camera_cfg.fps > 0:
            cap.set(self._cv2.CAP_PROP_FPS, self._camera_cfg.fps)
        self._cap = cap
        log.info("WebRTC camera capture opened (device=%s)", device_str)

