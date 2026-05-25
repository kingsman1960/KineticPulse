"""Streaming video capture with pluggable sources.

Sources are constructed via :func:`build_source` from a :class:`CameraConfig`.
All concrete sources use OpenCV's ``VideoCapture`` for portability; the
GStreamer pipeline strings are written to take advantage of NVDEC /
``nvarguscamerasrc`` on Jetson when OpenCV has been built with GStreamer
support (the JetPack OpenCV does).

The :class:`FrameQueue` is a thread-safe bounded queue with drop-oldest
backpressure to keep latency bounded (PRD: tight time-sync).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from queue import Empty, Full, Queue
from typing import Optional, Union

import numpy as np

from kineticpulse.config import CameraConfig
from kineticpulse.utils.logging import get_logger
from kineticpulse.utils.timing import now_ms

log = get_logger(__name__)


@dataclass
class Frame:
    """A single captured frame with a monotonic timestamp."""

    image: np.ndarray            # BGR HxWxC uint8
    timestamp_ms: int
    seq: int = 0


class FrameQueue:
    """Bounded FIFO that drops the oldest frame when full (latency-first)."""

    def __init__(self, maxsize: int = 2) -> None:
        self._q: Queue[Frame] = Queue(maxsize=maxsize)
        self._dropped = 0

    def put(self, frame: Frame) -> None:
        try:
            self._q.put_nowait(frame)
        except Full:
            try:
                self._q.get_nowait()
                self._dropped += 1
            except Empty:
                pass
            try:
                self._q.put_nowait(frame)
            except Full:
                self._dropped += 1

    def get(self, timeout: Optional[float] = 1.0) -> Optional[Frame]:
        try:
            return self._q.get(timeout=timeout)
        except Empty:
            return None

    @property
    def dropped(self) -> int:
        return self._dropped

    def qsize(self) -> int:
        return self._q.qsize()


class FrameSource:
    """Base class. Concrete sources override :meth:`_pipeline`."""

    def __init__(self, cfg: CameraConfig) -> None:
        self.cfg = cfg
        self._cap = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._seq = 0
        self.queue = FrameQueue(maxsize=2)

    def _pipeline(self) -> Union[str, int]:  # pragma: no cover - subclass duty
        raise NotImplementedError

    def open(self) -> None:
        import cv2

        spec = self._pipeline()
        if isinstance(spec, str):
            self._cap = cv2.VideoCapture(spec, cv2.CAP_GSTREAMER)
            if not self._cap.isOpened():
                log.warning("GStreamer pipeline failed, falling back to default backend.")
                self._cap = cv2.VideoCapture(spec)
        else:
            self._cap = cv2.VideoCapture(spec)
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cfg.width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg.height)
            self._cap.set(cv2.CAP_PROP_FPS, self.cfg.fps)

        if not self._cap.isOpened():
            raise RuntimeError(f"Failed to open camera source: {spec!r}")
        log.info("Camera opened: %s (%dx%d @ %d FPS desired)",
                 type(self).__name__, self.cfg.width, self.cfg.height, self.cfg.fps)

    def start(self) -> None:
        if self._cap is None:
            self.open()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="capture", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def _loop(self) -> None:
        backoff = 0.1
        while not self._stop.is_set():
            ok, img = self._cap.read()
            if not ok or img is None:
                log.warning("Frame read failed; retrying in %.2fs", backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2.0, 2.0)
                continue
            backoff = 0.1
            self._seq += 1
            self.queue.put(Frame(image=img, timestamp_ms=now_ms(), seq=self._seq))


class UsbWebcam(FrameSource):
    def _pipeline(self) -> Union[str, int]:
        try:
            return int(self.cfg.device)
        except ValueError:
            return self.cfg.device


class CsiCamera(FrameSource):
    def _pipeline(self) -> str:
        sensor_id = int(self.cfg.device) if str(self.cfg.device).isdigit() else 0
        return (
            f"nvarguscamerasrc sensor-id={sensor_id} ! "
            f"video/x-raw(memory:NVMM),width={self.cfg.width},height={self.cfg.height},"
            f"framerate={self.cfg.fps}/1,format=NV12 ! "
            f"nvvidconv ! video/x-raw,format=BGRx ! videoconvert ! "
            f"video/x-raw,format=BGR ! appsink drop=true max-buffers=1"
        )


class RtspStream(FrameSource):
    def _pipeline(self) -> str:
        return (
            f"rtspsrc location={self.cfg.device} latency=100 ! "
            f"rtph264depay ! h264parse ! nvv4l2decoder ! "
            f"nvvidconv ! video/x-raw,format=BGRx ! videoconvert ! "
            f"video/x-raw,format=BGR ! appsink drop=true max-buffers=1"
        )


class FileSource(FrameSource):
    """For testing: read frames from a video file."""

    def _pipeline(self) -> str:
        return self.cfg.device


def build_source(cfg: CameraConfig) -> FrameSource:
    """Construct the appropriate :class:`FrameSource` for ``cfg.source``."""
    source = (cfg.source or "usb").lower()
    if source == "usb":
        return UsbWebcam(cfg)
    if source == "csi":
        return CsiCamera(cfg)
    if source == "rtsp":
        return RtspStream(cfg)
    if source == "file":
        return FileSource(cfg)
    raise ValueError(f"Unknown camera source: {cfg.source!r}")
