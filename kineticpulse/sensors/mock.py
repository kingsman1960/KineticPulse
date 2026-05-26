"""Synthetic sensor source - transport-agnostic.

Used when ``--mock-ble`` (legacy name kept for CLI back-compat) is
passed to :mod:`kineticpulse.main`. Lets the rest of the pipeline run
end-to-end without any wristband - real BLE peripheral, real ESP32 over
TCP, or otherwise.

Originally lived inside :mod:`kineticpulse.sensors.ble` and was called
``MockBleClient`` because BLE was the only transport. The class has
nothing to do with BLE specifically: it just produces
:class:`~kineticpulse.sensors.parser.SensorEvent` instances on a
schedule. With the TCP transport now being the primary path, the class
moved here under the more accurate name ``MockSensorClient``. The
``MockBleClient`` alias at the bottom of this module preserves any old
imports.
"""

from __future__ import annotations

import asyncio
import math
import random
from typing import Optional, Tuple

from kineticpulse.config import WristbandConfig
from kineticpulse.sensors.parser import (
    AccelSample,
    HrSample,
    PulseLost,
    SensorEvent,
)
from kineticpulse.utils.logging import get_logger
from kineticpulse.utils.timing import now_ms

log = get_logger(__name__)


class MockSensorClient:
    """Synthesise telemetry without any hardware.

    Default behaviour: resting baseline (HR ~72 BPM, gravity-dominant
    accelerometer). The scenario can be scripted via the ``scenario``
    argument. Respects ``WristbandConfig.has_accelerometer`` so that
    HR-only operation mirrors current hardware status (no IMU yet).
    """

    SCENARIOS = ("resting", "fall_a_standard", "fall_b_seizure", "fall_c_syncope")

    def __init__(
        self,
        cfg: WristbandConfig,
        events: "asyncio.Queue[SensorEvent]",
        scenario: str = "resting",
        accel_hz: int = 50,
        hr_hz: float = 1.0,
        seed: int = 0,
    ) -> None:
        self.cfg = cfg
        self.events = events
        self.scenario = scenario
        self.accel_hz = accel_hz
        self.hr_hz = hr_hz
        self._stop = asyncio.Event()
        self._rng = random.Random(seed)
        self._fall_at_s: Optional[float] = None

    async def run(self) -> None:
        log.info(
            "MockSensorClient: scenario=%s accel=%s hr=%.2fHz",
            self.scenario,
            f"{self.accel_hz}Hz" if self.cfg.has_accelerometer else "DISABLED (no IMU)",
            self.hr_hz,
        )
        t0_ms = now_ms()
        if self.scenario != "resting":
            self._fall_at_s = 5.0   # let the rest of the pipeline warm up

        loops = [self._hr_loop(t0_ms)]
        if self.cfg.has_accelerometer:
            loops.append(self._accel_loop(t0_ms))
        await asyncio.gather(*loops)

    async def _accel_loop(self, t0_ms: int) -> None:
        period = 1.0 / self.accel_hz
        while not self._stop.is_set():
            t_s = (now_ms() - t0_ms) / 1000.0
            ax, ay, az = self._accel_at(t_s)
            self._submit(AccelSample(ax=ax, ay=ay, az=az, timestamp_ms=now_ms()))
            await asyncio.sleep(period)

    async def _hr_loop(self, t0_ms: int) -> None:
        period = 1.0 / self.hr_hz
        while not self._stop.is_set():
            t_s = (now_ms() - t0_ms) / 1000.0
            bpm = self._hr_at(t_s)
            if bpm is None:
                self._submit(PulseLost(duration_s=period, timestamp_ms=now_ms()))
            else:
                self._submit(HrSample(bpm=bpm, timestamp_ms=now_ms()))
            await asyncio.sleep(period)

    def stop(self) -> None:
        self._stop.set()

    def _submit(self, ev: SensorEvent) -> None:
        try:
            self.events.put_nowait(ev)
        except asyncio.QueueFull:
            try:
                _ = self.events.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self.events.put_nowait(ev)

    def _accel_at(self, t_s: float) -> Tuple[float, float, float]:
        """Synthesise the accel signal at time ``t_s``."""
        noise = lambda: self._rng.gauss(0.0, 0.02)
        if self.scenario == "resting":
            return (noise(), noise(), 1.0 + noise())

        if self._fall_at_s is None or t_s < self._fall_at_s:
            return (noise(), noise(), 1.0 + noise())

        dt = t_s - self._fall_at_s
        if self.scenario == "fall_a_standard":
            if 0 <= dt < 0.15:
                return (4.0 + noise(), 0.0 + noise(), 4.5 + noise())   # impact spike
            return (noise(), noise(), 1.0 + noise())                   # stillness
        if self.scenario == "fall_b_seizure":
            if 0 <= dt < 0.15:
                return (5.0 + noise(), 0.0 + noise(), 4.5 + noise())
            tremor = math.sin(2 * math.pi * 5.0 * dt) * 0.4
            return (tremor + noise(), tremor + noise(), 1.0 + noise())
        if self.scenario == "fall_c_syncope":
            if 0 <= dt < 0.15:
                return (2.5 + noise(), 0.0 + noise(), 3.0 + noise())   # softer collapse
            return (noise(), noise(), 1.0 + noise())
        return (noise(), noise(), 1.0 + noise())

    def _hr_at(self, t_s: float) -> Optional[int]:
        baseline = 72
        jitter = self._rng.randint(-2, 2)
        if self.scenario == "resting" or self._fall_at_s is None or t_s < self._fall_at_s:
            return baseline + jitter
        dt = t_s - self._fall_at_s
        if self.scenario == "fall_a_standard":
            return min(125, baseline + int(dt * 35) + jitter)
        if self.scenario == "fall_b_seizure":
            return min(170, baseline + int(dt * 90) + jitter)
        if self.scenario == "fall_c_syncope":
            if dt > 2.0:
                return None    # pulse lost
            return max(40, baseline - int(dt * 25) + jitter)
        return baseline + jitter


# Back-compat alias for any imports still referencing the old name.
MockBleClient = MockSensorClient
