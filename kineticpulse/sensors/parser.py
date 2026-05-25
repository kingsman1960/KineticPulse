"""Telemetry decoding for the KineticPulse wristband.

The wristband transmits two streams over BLE:

- **Accelerometer** : little-endian ``int16`` x/y/z at 100 Hz, ``+/- 8 g``.
  Each int16 ``a_raw`` maps to acceleration in g as
  ``a_g = a_raw * (8 / 32768)``.
- **Heart rate**    : the Bluetooth SIG standard
  *Heart Rate Measurement* characteristic (UUID ``0x2A37``).

The structures here are intentionally minimal and BLE-stack-agnostic so
the same parser is reused by the mock client.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Optional, Union


# Convert raw int16 accel readings to g.
ACCEL_RANGE_G = 8.0
ACCEL_INT_TO_G = ACCEL_RANGE_G / 32768.0


@dataclass
class AccelSample:
    """Single 3-axis acceleration sample in g."""

    ax: float
    ay: float
    az: float
    timestamp_ms: int

    @property
    def magnitude_g(self) -> float:
        return math.sqrt(self.ax * self.ax + self.ay * self.ay + self.az * self.az)


@dataclass
class HrSample:
    """Single heart-rate sample in BPM."""

    bpm: int
    timestamp_ms: int


@dataclass
class PulseLost:
    """Synthesised event when the wristband reports no pulse for too long."""

    duration_s: float
    timestamp_ms: int


SensorEvent = Union[AccelSample, HrSample, PulseLost]


def parse_accel_packet(data: bytes, timestamp_ms: int) -> Optional[AccelSample]:
    """Parse a 6-byte ``<hhh`` accelerometer packet from the wristband.

    Returns ``None`` for malformed packets so the BLE client can simply
    log and continue.
    """
    if len(data) < 6:
        return None
    try:
        ax_raw, ay_raw, az_raw = struct.unpack("<hhh", data[:6])
    except struct.error:
        return None
    return AccelSample(
        ax=ax_raw * ACCEL_INT_TO_G,
        ay=ay_raw * ACCEL_INT_TO_G,
        az=az_raw * ACCEL_INT_TO_G,
        timestamp_ms=timestamp_ms,
    )


def parse_hr_packet(data: bytes, timestamp_ms: int) -> Optional[HrSample]:
    """Parse a Bluetooth SIG Heart Rate Measurement characteristic value.

    Spec:
      byte 0    : flags (bit 0 = HR value is uint16 instead of uint8)
      byte 1..  : HR value (uint8 or uint16 LE depending on flags)
    """
    if len(data) < 2:
        return None
    flags = data[0]
    try:
        if flags & 0x01:
            if len(data) < 3:
                return None
            (bpm,) = struct.unpack_from("<H", data, 1)
        else:
            bpm = data[1]
    except struct.error:
        return None
    return HrSample(bpm=int(bpm), timestamp_ms=timestamp_ms)
