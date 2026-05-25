"""Tests for MAX30102 raw-PPG handling (parser + on-Jetson HR processor)."""

from __future__ import annotations

import math
import struct
from typing import List

import pytest

from kineticpulse.sensors.parser import HrSample
from kineticpulse.sensors.ppg import PpgProcessor, PpgSample, parse_ppg_packet


# --------------------------------------------------------------------------- #
# parse_ppg_packet
# --------------------------------------------------------------------------- #


def _encode_packet(samples: List[tuple]) -> bytes:
    """Pack (ir, red) tuples into the wire format the parser expects."""
    buf = bytearray()
    for ir, red in samples:
        buf += struct.pack("<II", ir, red)
    return bytes(buf)


def test_parse_ppg_packet_roundtrip_single_sample() -> None:
    data = _encode_packet([(123_456, 65_432)])
    out = parse_ppg_packet(data, base_timestamp_ms=10_000, sample_rate_hz=100)
    assert len(out) == 1
    assert out[0].ir == 123_456
    assert out[0].red == 65_432
    assert out[0].timestamp_ms == 10_000


def test_parse_ppg_packet_multi_sample_timestamps_step_back() -> None:
    samples = [(100, 200), (110, 210), (120, 220), (130, 230)]
    data = _encode_packet(samples)
    out = parse_ppg_packet(data, base_timestamp_ms=10_000, sample_rate_hz=100)
    assert [s.ir for s in out] == [100, 110, 120, 130]
    assert out[-1].timestamp_ms == 10_000
    # 100 Hz -> 10 ms between samples, last sample at base, earlier ones step back
    expected = [10_000 - 30, 10_000 - 20, 10_000 - 10, 10_000]
    assert [s.timestamp_ms for s in out] == expected


def test_parse_ppg_packet_empty_and_malformed_are_safe() -> None:
    assert parse_ppg_packet(b"", 0) == []
    # 5 bytes is shorter than one sample (8 bytes) -> nothing decoded.
    assert parse_ppg_packet(b"\x00\x01\x02\x03\x04", 0) == []


# --------------------------------------------------------------------------- #
# PpgProcessor
# --------------------------------------------------------------------------- #


def _synthesize_ppg(bpm: float, fs: int = 100, duration_s: float = 12.0,
                    dc_offset: int = 100_000, amplitude: int = 8_000) -> List[PpgSample]:
    """Build a clean synthetic PPG signal at the requested BPM."""
    samples: List[PpgSample] = []
    f_hz = bpm / 60.0
    n = int(duration_s * fs)
    for i in range(n):
        t = i / fs
        # Sharper-than-sin pulse shape: positive-half-cycle clipped sine.
        s = math.sin(2 * math.pi * f_hz * t)
        peak_shape = max(0.0, s) ** 1.5
        ir = int(dc_offset + amplitude * peak_shape)
        samples.append(PpgSample(ir=ir, red=ir, timestamp_ms=int(t * 1000)))
    return samples


@pytest.mark.parametrize("target_bpm", [55, 72, 95, 130])
def test_processor_recovers_bpm_within_5(target_bpm: int) -> None:
    proc = PpgProcessor(sample_rate_hz=100, window_s=8.0, output_period_s=1.0,
                        smoothing=0.0)
    samples = _synthesize_ppg(bpm=float(target_bpm))
    outputs: List[HrSample] = []
    for s in samples:
        hr = proc.push(s)
        if hr is not None:
            outputs.append(hr)
    assert outputs, "processor produced no HR estimates"
    estimated = outputs[-1].bpm
    assert abs(estimated - target_bpm) <= 5, (
        f"BPM estimate {estimated} too far from target {target_bpm}"
    )


def test_processor_returns_none_before_warmup() -> None:
    proc = PpgProcessor(sample_rate_hz=100, window_s=8.0, output_period_s=1.0)
    # Push only 1 s of data; below the 2 s minimum.
    samples = _synthesize_ppg(bpm=70.0, duration_s=1.0)
    outputs = [proc.push(s) for s in samples]
    assert all(o is None for o in outputs)


def test_processor_rejects_invalid_sample_rate() -> None:
    with pytest.raises(ValueError):
        PpgProcessor(sample_rate_hz=0)


def test_processor_reset_clears_state() -> None:
    proc = PpgProcessor(sample_rate_hz=100)
    for s in _synthesize_ppg(bpm=70.0, duration_s=4.0):
        proc.push(s)
    assert proc.latest_bpm is not None
    proc.reset()
    assert proc.latest_bpm is None
