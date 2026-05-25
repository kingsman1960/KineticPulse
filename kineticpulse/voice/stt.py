"""Local speech-to-text for the verification phase.

The production stack uses ``faster-whisper`` (a CTranslate2-backed
implementation of Whisper) running on CUDA on the Jetson Orin Nano.
On a dev laptop, the same code path works on CPU as well.

The mock implementation reads from a pre-recorded WAV or returns a
configured string after a delay; it lets the rest of the pipeline run
without a microphone.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from kineticpulse.config import VoiceConfig
from kineticpulse.utils.logging import get_logger
from kineticpulse.utils.timing import now_ms

log = get_logger(__name__)


@dataclass
class SttResult:
    """Result of a single utterance transcription."""

    text: str
    confidence: float
    duration_s: float
    timestamp_ms: int


class WhisperStt:
    """``faster-whisper`` based STT (Whisper small.en by default)."""

    def __init__(self, cfg: VoiceConfig) -> None:
        self.cfg = cfg
        self._model = None
        self._lock = threading.Lock()

    def load(self) -> None:
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ImportError(
                "faster-whisper not installed. Install it on the Jetson, "
                "or run with --mock-stt for development."
            ) from exc
        compute = "int8" if self.cfg.stt_device == "cpu" else "float16"
        device = "auto" if self.cfg.stt_device in ("", "auto") else self.cfg.stt_device
        log.info("Loading Whisper STT model=%s device=%s compute=%s",
                 self.cfg.stt_model, device, compute)
        self._model = WhisperModel(self.cfg.stt_model, device=device, compute_type=compute)

    async def listen_once(self, duration_s: Optional[float] = None) -> SttResult:
        """Record from the default microphone and transcribe."""
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise ImportError(
                "sounddevice not installed. Install it, or run with --mock-stt."
            ) from exc

        self.load()
        timeout = float(duration_s or self.cfg.verify_timeout_s)
        sample_rate = 16000
        log.info("STT: recording up to %.1fs of audio", timeout)
        audio = sd.rec(int(timeout * sample_rate), samplerate=sample_rate,
                       channels=1, dtype="float32")
        sd.wait()
        audio = np.asarray(audio).reshape(-1)

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._transcribe, audio, sample_rate)

    def _transcribe(self, audio: np.ndarray, sample_rate: int) -> SttResult:
        with self._lock:
            t0 = time.monotonic()
            segments, info = self._model.transcribe(audio, language="en", beam_size=1)
            text_parts = []
            for seg in segments:
                text_parts.append(seg.text)
            text = " ".join(text_parts).strip()
            confidence = float(getattr(info, "language_probability", 1.0))
            return SttResult(
                text=text,
                confidence=confidence,
                duration_s=time.monotonic() - t0,
                timestamp_ms=now_ms(),
            )


class MockStt:
    """Return a canned utterance after the configured timeout."""

    def __init__(self, cfg: VoiceConfig, response: str = "", delay_s: float = 1.5) -> None:
        self.cfg = cfg
        self.response = response
        self.delay_s = delay_s

    def load(self) -> None:
        return

    async def listen_once(self, duration_s: Optional[float] = None) -> SttResult:
        delay = min(self.delay_s, float(duration_s or self.cfg.verify_timeout_s))
        await asyncio.sleep(delay)
        return SttResult(
            text=self.response,
            confidence=1.0,
            duration_s=delay,
            timestamp_ms=now_ms(),
        )


def build_stt(cfg: VoiceConfig, *, mock: bool = False, mock_response: str = "") -> "WhisperStt | MockStt":
    if mock:
        return MockStt(cfg, response=mock_response)
    return WhisperStt(cfg)
