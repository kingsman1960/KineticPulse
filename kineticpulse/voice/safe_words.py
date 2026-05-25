"""Classify the subject's verbal response after a fall prompt.

Three possible verdicts:

* ``SAFE``     - subject explicitly indicated they are fine.
* ``DISTRESS`` - subject called for help or expressed pain / panic.
* ``UNKNOWN``  - no clear keyword detected (caller may treat this as
  silence after the verify timeout).
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Iterable, Optional, Tuple


class VoiceVerdict(str, Enum):
    SAFE = "safe"
    DISTRESS = "distress"
    UNKNOWN = "unknown"


def _normalise(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _contains_any(haystack: str, phrases: Iterable[str]) -> Optional[str]:
    for phrase in phrases:
        if not phrase:
            continue
        pat = r"(^|\s)" + re.escape(phrase.lower()) + r"(\s|$)"
        if re.search(pat, haystack):
            return phrase
    return None


def classify_response(
    text: Optional[str],
    safe_words: Iterable[str],
    distress_words: Iterable[str],
) -> Tuple[VoiceVerdict, Optional[str]]:
    """Return ``(verdict, matched_phrase_or_None)``.

    Distress words take priority over safe words: a subject who says
    ``"I'm fine, but it hurts"`` should be flagged as distress.
    """
    if not text or not text.strip():
        return VoiceVerdict.UNKNOWN, None
    normalised = _normalise(text)
    distress = _contains_any(normalised, [w.lower() for w in distress_words])
    if distress:
        return VoiceVerdict.DISTRESS, distress
    safe = _contains_any(normalised, [w.lower() for w in safe_words])
    if safe:
        return VoiceVerdict.SAFE, safe
    return VoiceVerdict.UNKNOWN, None
