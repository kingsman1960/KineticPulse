"""Safe dashboard demo: rest → PPG crash → collapse → syncope → seizure."""

from __future__ import annotations

from kineticpulse.sensors.mock import (
    DEMO_COLLAPSE_S,
    DEMO_PULSE_LOST_S,
    DEMO_REST_S,
    DEMO_SEIZURE_S,
    demo_syncope_seizure_accel,
    demo_syncope_seizure_hr,
)
from kineticpulse.sensors.parser import AccelSample, HrSample, PulseLost
from kineticpulse.fusion.rules import accel_signature, aggregate_hr, hr_signature, HrSignature
from kineticpulse.config import ThresholdsConfig


def _mag(ax: float, ay: float, az: float) -> float:
    return (ax * ax + ay * ay + az * az) ** 0.5


def test_demo_hr_phases():
    assert abs(demo_syncope_seizure_hr(1.0) - 72) <= 2
    mid = demo_syncope_seizure_hr(10.0)
    assert mid is not None and 40 <= mid <= 60
    assert demo_syncope_seizure_hr(15.0) is None
    late = demo_syncope_seizure_hr(20.0)
    assert late is not None and late >= 130


def test_demo_accel_impact_then_tremor():
    rest = demo_syncope_seizure_accel(1.0, 0.0, 0.0)
    assert abs(_mag(*rest) - 1.0) < 0.05
    impact = demo_syncope_seizure_accel(DEMO_COLLAPSE_S + 0.05, 0.0, 0.0)
    assert _mag(*impact) >= 3.0
    still = demo_syncope_seizure_accel(16.0, 0.0, 0.0)
    assert abs(_mag(*still) - 1.0) < 0.05
    spike = demo_syncope_seizure_accel(DEMO_SEIZURE_S + 0.05, 0.0, 0.05)
    assert _mag(*spike) >= 3.0


def test_demo_timeline_is_in_order():
    assert DEMO_REST_S < DEMO_COLLAPSE_S < DEMO_PULSE_LOST_S < DEMO_SEIZURE_S


def test_demo_tremor_tail_classifies_as_impact_tremor():
    """Seizure phase must keep a 3 g spike inside the 4 s fusion window."""
    samples = []
    t0 = 19_000
    for i in range(200):
        t_s = DEMO_SEIZURE_S + i * 0.02
        ax, ay, az = demo_syncope_seizure_accel(t_s, 0.0, t_s - DEMO_SEIZURE_S)
        samples.append(AccelSample(ax=ax, ay=ay, az=az, timestamp_ms=t0 + i * 20))
    sig = accel_signature(samples, ThresholdsConfig())
    assert sig.value == "impact_tremor"


def test_recovered_hr_clears_stale_pulse_lost():
    """A beat after pulse-loss must not stay classified as arrest."""
    samples = [
        PulseLost(duration_s=1.0, timestamp_ms=1_000),
        PulseLost(duration_s=1.0, timestamp_ms=2_000),
        HrSample(bpm=140, timestamp_ms=8_000),
    ]
    agg = aggregate_hr(samples, now_ms=8_200)
    assert agg.latest_bpm == 140
    assert agg.pulse_lost_s < 3.0
    assert hr_signature(agg, ThresholdsConfig()) == HrSignature.SEIZURE_SPIKE
