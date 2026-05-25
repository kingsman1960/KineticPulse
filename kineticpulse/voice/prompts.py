"""Offline TTS prompts.

Uses :mod:`pyttsx3` when available (works on Windows / macOS / Linux without
any cloud dependency). Falls back to printing the prompt to stdout in
test environments where audio output is unavailable.
"""

from __future__ import annotations

import threading
from typing import Optional

from kineticpulse.utils.logging import get_logger

log = get_logger(__name__)


class PromptPlayer:
    """Play short voice prompts. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._engine = None
        try:
            import pyttsx3
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", 175)
        except Exception as exc:
            log.warning("pyttsx3 unavailable (%s); prompts will be logged only.", exc)
            self._engine = None

    def say(self, text: str) -> None:
        log.info("VOICE PROMPT: %s", text)
        if self._engine is None:
            return
        with self._lock:
            try:
                self._engine.say(text)
                self._engine.runAndWait()
            except Exception as exc:
                log.warning("TTS playback failed: %s", exc)
