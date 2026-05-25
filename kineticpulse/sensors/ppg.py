"""MAX30102 raw PPG support.

The hardware team's current direction is to have the ESP32 stream the
MAX30102's raw PPG samples (IR + Red channels) over BLE rather than
running peak detection on the microcontroller. This module turns those
raw samples into the :class:`HrSample` events the fusion engine already
understands.

Two pieces:

- :func:`parse_ppg_packet` decodes the wire format. The default packing
  is ``<II`` (two little-endian uint32: IR then Red) per sample, which is
  the natural mapping for MAX30102's 18-bit FIFO entries padded to 32-bit.
  Update the format string here if the firmware uses something different.
- :class:`PpgProcessor` is a small, dependency-free heart-rate estimator:
  moving-average detrending, peak detection with a refractory period,
  and BPM from average inter-peak interval over a sliding window.

The algorithm is deliberately simple (no SciPy) so it runs anywhere and
is easy to reason about. Swap for `heartpy` or a SciPy-based pipeline if
clinical-grade HRV becomes a requirement.
"""

from __future__ import annotations

import collections
import struct
from dataclasses import dataclass
from typing import Deque, List, Optional, Tuple

from kineticpulse.sensors.parser import HrSample
from kineticpulse.utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class PpgSample:
    """Single raw PPG reading from the MAX30102 (or compatible sensor)."""

    ir: int
    red: int
    timestamp_ms: int


def parse_ppg_packet(
    data: bytes,
    base_timestamp_ms: int,
    sample_rate_hz: int = 100,
) -> List[PpgSample]:
    """Decode a BLE packet of N raw PPG samples.

    Layout (default): little-endian ``<II`` per sample - 4 bytes IR then
    4 bytes Red. Each sample is timestamped relative to ``base_timestamp_ms``
    such that the **last** sample in the packet is at ``base_timestamp_ms``
    and earlier samples step backwards by ``1000 / sample_rate_hz`` ms.

    Returns an empty list for malformed packets (the caller logs and
    continues). The function never raises.
    """
    n = len(data) // 8
    if n <= 0:
        return []
    period_ms = 1000.0 / max(1, sample_rate_hz)
    samples: List[PpgSample] = []
    for i in range(n):
        try:
            ir, red = struct.unpack_from("<II", data, i * 8)
        except struct.error:
            return samples
        ts = int(base_timestamp_ms - (n - 1 - i) * period_ms)
        samples.append(PpgSample(ir=int(ir), red=int(red), timestamp_ms=ts))
    return samples


class PpgProcessor:
    """Convert a stream of :class:`PpgSample` into :class:`HrSample` events.

    Pipeline:

    1. **Detrend** - subtract a centred moving average (window = ``fs/2`` samples)
       to remove the slow DC drift of the IR channel.
    2. **Peak detect** - find local maxima above a fraction of the
       detrended window's peak amplitude, with a refractory period that
       caps the implied HR at ~240 BPM.
    3. **BPM** - average inter-peak intervals across the working window.
       Optional exponential smoothing keeps the output stable when one
       beat is mis-detected.
    """

    def __init__(
        self,
        sample_rate_hz: int = 100,
        window_s: float = 8.0,
        output_period_s: float = 1.0,
        min_bpm: float = 30.0,
        max_bpm: float = 220.0,
        smoothing: float = 0.4,
    ) -> None:
        if sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive")
        self.fs = int(sample_rate_hz)
        self.window_s = float(window_s)
        self.output_period_ms = int(output_period_s * 1000)
        self.min_bpm = float(min_bpm)
        self.max_bpm = float(max_bpm)
        self.smoothing = float(smoothing)
        self._buffer: Deque[Tuple[int, int]] = collections.deque(
            maxlen=int(self.window_s * self.fs)
        )
        self._last_output_ts_ms = 0
        self._last_bpm: Optional[float] = None

    @property
    def latest_bpm(self) -> Optional[float]:
        return self._last_bpm

    def push(self, sample: PpgSample) -> Optional[HrSample]:
        """Push one PPG sample. Returns an :class:`HrSample` when an
        updated BPM is ready (roughly once per ``output_period_s``)."""
        self._buffer.append((sample.timestamp_ms, sample.ir))
        if sample.timestamp_ms - self._last_output_ts_ms < self.output_period_ms:
            return None
        # Need at least 2 s of data and 3 peaks (heuristic) to estimate BPM.
        if len(self._buffer) < self.fs * 2:
            return None
        bpm = self._estimate_bpm()
        if bpm is None:
            return None
        if self._last_bpm is not None:
            bpm = self.smoothing * self._last_bpm + (1.0 - self.smoothing) * bpm
        self._last_bpm = bpm
        self._last_output_ts_ms = sample.timestamp_ms
        return HrSample(bpm=int(round(bpm)), timestamp_ms=sample.timestamp_ms)

    def reset(self) -> None:
        self._buffer.clear()
        self._last_output_ts_ms = 0
        self._last_bpm = None

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _estimate_bpm(self) -> Optional[float]:
        timestamps = [t for t, _ in self._buffer]
        ir_values = [float(v) for _, v in self._buffer]
        if not ir_values:
            return None

        # Centred moving-average detrender. Window = ~0.5 s for a clean
        # AC component that preserves heartbeat peaks.
        half = max(1, self.fs // 4)
        detrended: List[float] = []
        running_sum = 0.0
        # Use cumulative sums for O(N) detrending.
        cum = [0.0]
        for v in ir_values:
            cum.append(cum[-1] + v)
        n = len(ir_values)
        for i in range(n):
            lo = max(0, i - half)
            hi = min(n, i + half + 1)
            local_mean = (cum[hi] - cum[lo]) / (hi - lo)
            detrended.append(ir_values[i] - local_mean)

        peak_amp = max((abs(v) for v in detrended), default=0.0)
        if peak_amp <= 0.0:
            return None
        threshold = 0.35 * peak_amp

        # Refractory period: cap implied HR at max_bpm
        refractory_samples = max(1, int(self.fs * 60.0 / self.max_bpm))
        peaks: List[int] = []
        last_peak = -refractory_samples
        for i in range(1, n - 1):
            if i - last_peak < refractory_samples:
                continue
            v = detrended[i]
            if v >= threshold and v > detrended[i - 1] and v >= detrended[i + 1]:
                peaks.append(i)
                last_peak = i

        if len(peaks) < 2:
            return None

        min_interval_ms = 60_000.0 / self.max_bpm
        max_interval_ms = 60_000.0 / self.min_bpm
        intervals_ms: List[float] = []
        for j in range(1, len(peaks)):
            dt_ms = float(timestamps[peaks[j]] - timestamps[peaks[j - 1]])
            if min_interval_ms <= dt_ms <= max_interval_ms:
                intervals_ms.append(dt_ms)

        if not intervals_ms:
            return None

        avg_interval_ms = sum(intervals_ms) / len(intervals_ms)
        if avg_interval_ms <= 0.0:
            return None
        bpm = 60_000.0 / avg_interval_ms
        if not (self.min_bpm <= bpm <= self.max_bpm):
            return None
        return bpm
