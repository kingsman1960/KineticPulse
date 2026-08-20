"""Keyword classifier must accept English and German replies.

The speaker language is not known in advance, so a German ``Hilfe`` or
``mir geht's gut`` has to classify the same way as the English equivalents.
"""

from __future__ import annotations

from kineticpulse.config import VoiceConfig
from kineticpulse.voice.safe_words import VoiceVerdict, classify_response
from kineticpulse.voice.stt import pick_stt_language

_CFG = VoiceConfig()


def _classify(text: str):
    return classify_response(text, _CFG.safe_words, _CFG.distress_words)


def test_english_safe_and_distress_still_match():
    assert _classify("I am fine")[0] == VoiceVerdict.SAFE
    assert _classify("help")[0] == VoiceVerdict.DISTRESS


def test_curly_apostrophe_does_not_drop_im_fine():
    """Whisper often emits a typographic quote; that used to become 'i m fine'."""
    verdict, matched = _classify("I’m fine")
    assert verdict == VoiceVerdict.SAFE
    assert matched is not None


def test_german_safe_replies():
    assert _classify("Mir geht es gut")[0] == VoiceVerdict.SAFE
    assert _classify("Mir geht's gut")[0] == VoiceVerdict.SAFE
    assert _classify("Alles in Ordnung")[0] == VoiceVerdict.SAFE


def test_german_distress_replies():
    assert _classify("Hilfe")[0] == VoiceVerdict.DISTRESS
    assert _classify("Notfall")[0] == VoiceVerdict.DISTRESS
    assert _classify("Das tut weh")[0] == VoiceVerdict.DISTRESS
    assert _classify("Schmerzen")[0] == VoiceVerdict.DISTRESS


def test_umlaut_folding_matches_listed_ascii_phrase():
    """Whisper emits 'Fürchte'; the lexicon stores the folded ASCII form."""
    verdict, matched = classify_response(
        "Fürchte mich",
        safe_words=[],
        distress_words=["fuerchte mich"],
    )
    assert verdict == VoiceVerdict.DISTRESS
    assert matched == "fuerchte mich"


def test_distress_still_wins_over_safe_in_either_language():
    assert _classify("I'm fine, but it hurts")[0] == VoiceVerdict.DISTRESS
    assert _classify("Mir geht es gut, aber Hilfe")[0] == VoiceVerdict.DISTRESS


def test_pick_stt_language_clamps_to_en_or_de():
    """A short 'Hilfe' often scores as Dutch; we must still transcribe as German."""
    probs = [("nl", 0.55), ("de", 0.30), ("en", 0.10), ("af", 0.05)]
    assert pick_stt_language(probs, ["en", "de"]) == "de"
    assert pick_stt_language(probs, ["en"]) == "en"
    assert pick_stt_language(probs, []) is None


def test_pick_stt_language_prefers_english_when_it_wins():
    probs = [("en", 0.8), ("de", 0.15), ("fr", 0.05)]
    assert pick_stt_language(probs, ["en", "de"]) == "en"
