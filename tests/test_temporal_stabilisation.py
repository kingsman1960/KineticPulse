"""Tests for the EMA + hysteresis stabilisation in ``TemporalHead``.

Models the live-test failure mode where a 1-2 second oscillation between
``sitting`` and ``falling`` appeared at posture-transition boundaries.
The stabilisation must:

1. Smooth raw probabilities via an exponential moving average so a single
   noisy frame doesn't flip the argmax.
2. Defer publishing a new ``stable_label`` until the same argmax has held
   for ``hysteresis_min_consecutive`` predictions in a row.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from kineticpulse.config import TemporalConfig
from kineticpulse.temporal.stgcn import KeypointRingBuffer, TemporalHead
from kineticpulse.temporal.types import ActionLogits


def _config(*, alpha: float = 0.4, min_consec: int = 3,
            window_size: int = 4, stride: int = 1,
            weights: str = "/path/that/does/not/exist") -> TemporalConfig:
    """A TemporalConfig that forces the heuristic fallback path so the
    tests never depend on the TSSTG checkpoint being present."""
    return TemporalConfig(
        enabled=True,
        window_size=window_size,
        stride=stride,
        weights=weights,
        smoothing_alpha=alpha,
        hysteresis_min_consecutive=min_consec,
    )


def _filled_buffer(n: int = 4) -> KeypointRingBuffer:
    buf = KeypointRingBuffer(maxlen=n)
    for _ in range(n):
        buf.push(np.zeros((17, 3), dtype=np.float32))
    return buf


def _drive_head(head: TemporalHead, distributions, *, ts_step: int = 100):
    """Feed a sequence of (fallen, falling, stand, sitting) tuples through
    the head as if they were the raw backend output, returning the list of
    stabilised ``ActionLogits``.

    We do this by monkey-patching the heuristic and TSSTG paths so the
    head sees exactly the distribution we hand it; everything else
    (EMA + hysteresis) is the real code under test.
    """
    out = []
    buf = _filled_buffer(head.cfg.window_size)
    for i, (f, fa, st, si) in enumerate(distributions):
        ts = (i + 1) * ts_step
        raw = ActionLogits(fallen=f, falling=fa, stand=st, sitting=si,
                           timestamp_ms=ts)
        head._predict_with_heuristic = staticmethod(  # type: ignore[assignment]
            lambda *_a, _r=raw, **_k: _r
        )
        head._classifier = None
        head._classifier_unavailable = True
        out.append(head.maybe_predict(buf, None, ts))
    return out


# --------------------------------------------------------------------------- #
# EMA smoothing
# --------------------------------------------------------------------------- #


def test_smoothed_probability_is_ema_of_raw_inputs():
    """alpha=0.5: smoothed = 0.5*new + 0.5*prev. After two identical
    inputs the smoothed value should equal the raw input (steady state),
    not the raw input alone."""
    head = TemporalHead(_config(alpha=0.5, min_consec=1))
    seq = [
        (0.0, 0.0, 1.0, 0.0),    # all stand
        (0.0, 0.0, 1.0, 0.0),    # still all stand
    ]
    out = _drive_head(head, seq)

    # First sample initialises the smoothed vector to the raw value.
    assert out[0].stand == pytest.approx(1.0)
    # Second sample equals the raw value (steady state at alpha=0.5).
    assert out[1].stand == pytest.approx(1.0)


def test_single_outlier_does_not_flip_smoothed_argmax():
    """A 5-frame run of strong 'stand' followed by one rogue 'falling'
    frame must not flip the smoothed argmax to 'falling'."""
    head = TemporalHead(_config(alpha=0.4, min_consec=1))
    # 5 strong stand frames, then a single falling outlier
    seq = [(0.0, 0.0, 1.0, 0.0)] * 5 + [(0.0, 0.95, 0.05, 0.0)]
    out = _drive_head(head, seq)

    smoothed_after_outlier = out[-1]
    # 0.4 * 0.95 + 0.6 * (close to 0) ~= 0.38 for falling
    # 0.4 * 0.05 + 0.6 * (close to 1) ~= 0.62 for stand
    # so smoothed argmax must still be stand.
    assert smoothed_after_outlier.argmax_label == "stand"
    assert smoothed_after_outlier.stand > smoothed_after_outlier.falling


# --------------------------------------------------------------------------- #
# Hysteresis
# --------------------------------------------------------------------------- #


def test_stable_label_holds_until_consecutive_threshold_reached():
    """min_consec=3: the stable_label should only update after 3
    consecutive raw argmax matches on the candidate."""
    head = TemporalHead(_config(alpha=1.0, min_consec=3))   # alpha=1 -> raw == smoothed

    # Frame 1-3: stand, stand, stand. Stable label settles at stand on f=3.
    out = _drive_head(head, [
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
    ])
    assert out[0].stable_label is None     # candidate=stand, count=1
    assert out[1].stable_label is None     # candidate=stand, count=2
    assert out[2].stable_label == "stand"  # count==3 -> latch

    # Now drift: 2 falling frames. Hysteresis must NOT publish a new
    # stable label yet (still equals 'stand').
    out2 = _drive_head(head, [
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
    ])
    for r in out2:
        assert r.stable_label == "stand", \
            "hysteresis must hold until candidate matches min_consec times"

    # Third matching falling frame -> stable label flips.
    out3 = _drive_head(head, [(0.0, 1.0, 0.0, 0.0)])
    assert out3[0].stable_label == "falling"


def test_oscillation_between_two_classes_keeps_stable_label_pinned():
    """Simulate the live-test failure: noisy alternation between sitting
    and falling. The stable_label must NOT oscillate with it; once
    'sitting' has latched, a single 'falling' frame must not knock it
    out, and the candidate counter resets when a non-matching frame
    appears."""
    head = TemporalHead(_config(alpha=0.4, min_consec=3))

    # Latch on 'sitting' first.
    _drive_head(head, [(0.0, 0.0, 0.0, 1.0)] * 6)
    assert head._stable_label == "sitting"

    # Oscillate: sit, fall, sit, fall, sit, fall (smoothed argmax may
    # alternate too, but never reaches min_consec for any single class
    # because the candidate counter resets each time the argmax differs).
    out = _drive_head(head, [
        (0.0, 0.9, 0.0, 0.1),
        (0.0, 0.1, 0.0, 0.9),
        (0.0, 0.9, 0.0, 0.1),
        (0.0, 0.1, 0.0, 0.9),
        (0.0, 0.9, 0.0, 0.1),
    ])
    # During the oscillation, the stable label must never leave 'sitting'.
    for r in out:
        assert r.stable_label == "sitting", (
            f"stable_label flipped to {r.stable_label!r} during oscillation; "
            "hysteresis is not protecting the published label"
        )


def test_min_consec_one_latches_immediately():
    """If a deployment wants zero hysteresis, min_consec=1 should make
    the stable_label track raw argmax frame-by-frame."""
    head = TemporalHead(_config(alpha=1.0, min_consec=1))
    out = _drive_head(head, [
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (1.0, 0.0, 0.0, 0.0),
    ])
    assert out[0].stable_label == "stand"
    assert out[1].stable_label == "falling"
    assert out[2].stable_label == "fallen"


# --------------------------------------------------------------------------- #
# ActionLogits.confidence_of helper
# --------------------------------------------------------------------------- #


def test_confidence_of_returns_zero_for_unknown_label():
    al = ActionLogits(fallen=0.1, falling=0.2, stand=0.4, sitting=0.3,
                      timestamp_ms=0)
    assert al.confidence_of("stand") == pytest.approx(0.4)
    assert al.confidence_of("???")  == pytest.approx(0.0)
