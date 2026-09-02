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

# Dashboard playbooks. Times are seconds from process start.
DEMO_SYNCOPE_SEIZURE = "demo_syncope_seizure"
DEMO_TRIP_FALL = "demo_trip_fall"
DEMO_NIGHT_SYNCOPE = "demo_night_syncope"
DEMO_TONIC_CLONIC = "demo_tonic_clonic"
DEMO_SILENT_SLUMP = "demo_silent_slump"

DEMO_REST_S = 8.0
DEMO_COLLAPSE_S = 12.0
DEMO_PULSE_LOST_S = 14.0
DEMO_SEIZURE_S = 19.0
TRIP_WALK_S = 7.0
TRIP_IMPACT_S = 10.3
NIGHT_GETUP_S = 8.0
NIGHT_CRUMPLE_S = 11.0
NIGHT_PULSE_LOST_S = 16.0
TONIC_AURA_S = 6.0
TONIC_DROP_S = 11.0
SLUMP_FIDGET_S = 8.0
SLUMP_S = 14.0

# CLI --demo NAME → mock scenario. Keep hyphenated names; mock ids stay snake_case.
DEMO_CLI = {
    "syncope-seizure": DEMO_SYNCOPE_SEIZURE,
    "trip-fall": DEMO_TRIP_FALL,
    "night-syncope": DEMO_NIGHT_SYNCOPE,
    "tonic-clonic": DEMO_TONIC_CLONIC,
    "silent-slump": DEMO_SILENT_SLUMP,
}
DEMO_PLAYBOOKS = frozenset(DEMO_CLI.values())
DEMO_NARRATION = {
    DEMO_SYNCOPE_SEIZURE: "rest 0–8s, PPG drop 8–12s, collapse 12s, pulse lost 14–19s, seizure from 19s",
    DEMO_TRIP_FALL: "gait 7–10s, trip/impact 10.3s, scramble, then still (panic HR, not seizure)",
    DEMO_NIGHT_SYNCOPE: "sit 0–8s, stand-up 8s, orthostatic HR drop, crumple 11s, pulse lost 16s",
    DEMO_TONIC_CLONIC: "aura 6–11s (HR climb), drop 11s, clonic 5 Hz from 11.2s",
    DEMO_SILENT_SLUMP: "sit 0–8s, fidget, slow chair-slide 14s, no hard impact",
}

MOCK_SCENARIOS = (
    "resting",
    "fall_a_standard",
    "fall_b_seizure",
    "fall_c_syncope",
    *DEMO_CLI.values(),
)


def demo_syncope_seizure_hr(t_s: float, jitter: int = 0) -> Optional[int]:
    """Scripted PPG for the demo. ``None`` means the pulse sample disappeared."""
    if t_s < DEMO_REST_S:
        return 72 + jitter
    if t_s < DEMO_COLLAPSE_S:
        frac = (t_s - DEMO_REST_S) / (DEMO_COLLAPSE_S - DEMO_REST_S)
        return max(38, int(72 - 30 * frac) + jitter)
    if t_s < DEMO_PULSE_LOST_S:
        return max(36, 42 + jitter)
    if t_s < DEMO_SEIZURE_S:
        return None
    return min(165, 130 + int((t_s - DEMO_SEIZURE_S) * 20) + jitter)


def demo_syncope_seizure_accel(
    t_s: float, noise: float, tremor_phase_s: float
) -> Tuple[float, float, float]:
    if t_s < DEMO_COLLAPSE_S:
        return (noise, noise, 1.0 + noise)
    if t_s < DEMO_COLLAPSE_S + 0.2:
        return (4.2 + noise, 0.2 + noise, 4.6 + noise)
    if t_s < DEMO_SEIZURE_S:
        return (noise, noise, 1.0 + noise)
    ds = t_s - DEMO_SEIZURE_S
    # Repeat a short 4 g jolt so the 4 s fusion window still contains an impact.
    if (ds % 2.0) < 0.15:
        return (4.0 + noise, 0.0 + noise, 4.3 + noise)
    tremor = math.sin(2 * math.pi * 5.0 * ds) * 0.4
    return (tremor + noise, tremor + noise, 1.0 + tremor + noise)


def _quiet(noise: float) -> Tuple[float, float, float]:
    return (noise, noise, 1.0 + noise)


def _tremor5(phase_s: float, noise: float, amp: float = 0.4) -> Tuple[float, float, float]:
    t = math.sin(2 * math.pi * 5.0 * phase_s) * amp
    return (t + noise, t + noise, 1.0 + t + noise)


def demo_trip_fall_hr(t_s: float, jitter: int = 0) -> Optional[int]:
    if t_s < TRIP_WALK_S:
        return 74 + jitter
    if t_s < TRIP_IMPACT_S:
        return 82 + jitter
    return min(118, 82 + int((t_s - TRIP_IMPACT_S) * 18) + jitter)


def demo_trip_fall_accel(t_s: float, noise: float) -> Tuple[float, float, float]:
    if t_s < TRIP_WALK_S:
        return _quiet(noise)
    if t_s < TRIP_IMPACT_S:
        swing = 0.45 * math.sin(2 * math.pi * 1.8 * t_s)
        return (swing + noise, noise, 1.0 + noise)
    dt = t_s - TRIP_IMPACT_S
    if dt < 0.18:
        return (4.4 + noise, 0.4 + noise, 3.1 + noise)
    if dt < 0.9:
        w = 0.55 * math.sin(2 * math.pi * 3.0 * dt)
        return (w + noise, 0.2 + noise, 1.0 + w + noise)
    return _quiet(noise)


def demo_night_syncope_hr(t_s: float, jitter: int = 0) -> Optional[int]:
    if t_s < NIGHT_GETUP_S:
        return 66 + jitter
    if t_s < NIGHT_CRUMPLE_S:
        frac = (t_s - NIGHT_GETUP_S) / (NIGHT_CRUMPLE_S - NIGHT_GETUP_S)
        return max(42, int(66 - 22 * frac) + jitter)
    if t_s < NIGHT_PULSE_LOST_S:
        return max(38, 44 + jitter)
    return None


def demo_night_syncope_accel(t_s: float, noise: float) -> Tuple[float, float, float]:
    if t_s < NIGHT_CRUMPLE_S:
        return _quiet(noise)
    dt = t_s - NIGHT_CRUMPLE_S
    if dt < 0.7:
        return (1.15 + noise, 0.35 + noise, 1.55 + noise)
    return _quiet(noise)


def demo_tonic_clonic_hr(t_s: float, jitter: int = 0) -> Optional[int]:
    if t_s < TONIC_AURA_S:
        return 78 + jitter
    if t_s < TONIC_DROP_S:
        frac = (t_s - TONIC_AURA_S) / (TONIC_DROP_S - TONIC_AURA_S)
        return min(145, int(90 + 50 * frac) + jitter)
    return min(165, 145 + int((t_s - TONIC_DROP_S) * 8) + jitter)


def demo_tonic_clonic_accel(t_s: float, noise: float) -> Tuple[float, float, float]:
    if t_s < TONIC_AURA_S:
        return _quiet(noise)
    if t_s < TONIC_DROP_S:
        fidget = 0.18 * math.sin(2 * math.pi * 1.2 * t_s)
        return (fidget + noise, fidget + noise, 1.0 + noise)
    dt = t_s - TONIC_DROP_S
    if dt < 0.2 or (dt % 3.2) < 0.12:
        return (4.3 + noise, 0.1 + noise, 4.1 + noise)
    return _tremor5(dt, noise)


def demo_silent_slump_hr(t_s: float, jitter: int = 0) -> Optional[int]:
    if t_s < SLUMP_FIDGET_S:
        return 72 + jitter
    return min(88, 72 + int((t_s - SLUMP_FIDGET_S) * 2) + jitter)


def demo_silent_slump_accel(t_s: float, noise: float) -> Tuple[float, float, float]:
    if t_s < SLUMP_FIDGET_S:
        return _quiet(noise)
    if t_s < SLUMP_S:
        fidget = 0.22 * math.sin(2 * math.pi * 0.8 * t_s)
        return (fidget + noise, noise, 1.0 + noise)
    dt = t_s - SLUMP_S
    if dt < 1.1:
        return (0.9 + noise, 0.25 + noise, 1.15 + noise)
    return _quiet(noise)


def demo_hr(scenario: str, t_s: float, jitter: int = 0) -> Optional[int]:
    if scenario == DEMO_SYNCOPE_SEIZURE:
        return demo_syncope_seizure_hr(t_s, jitter)
    if scenario == DEMO_TRIP_FALL:
        return demo_trip_fall_hr(t_s, jitter)
    if scenario == DEMO_NIGHT_SYNCOPE:
        return demo_night_syncope_hr(t_s, jitter)
    if scenario == DEMO_TONIC_CLONIC:
        return demo_tonic_clonic_hr(t_s, jitter)
    if scenario == DEMO_SILENT_SLUMP:
        return demo_silent_slump_hr(t_s, jitter)
    return 72 + jitter


def demo_accel(scenario: str, t_s: float, noise: float) -> Tuple[float, float, float]:
    if scenario == DEMO_SYNCOPE_SEIZURE:
        return demo_syncope_seizure_accel(t_s, noise, t_s - DEMO_SEIZURE_S)
    if scenario == DEMO_TRIP_FALL:
        return demo_trip_fall_accel(t_s, noise)
    if scenario == DEMO_NIGHT_SYNCOPE:
        return demo_night_syncope_accel(t_s, noise)
    if scenario == DEMO_TONIC_CLONIC:
        return demo_tonic_clonic_accel(t_s, noise)
    if scenario == DEMO_SILENT_SLUMP:
        return demo_silent_slump_accel(t_s, noise)
    return _quiet(noise)


def demo_posture(scenario: str, t_s: float) -> str:
    """Coarse detector class for --no-camera playbooks."""
    if scenario == DEMO_SYNCOPE_SEIZURE:
        return "fallen" if t_s >= DEMO_COLLAPSE_S else "stand"
    if scenario == DEMO_TRIP_FALL:
        if t_s < TRIP_IMPACT_S - 0.15:
            return "stand"
        if t_s < TRIP_IMPACT_S + 0.4:
            return "falling"
        return "fallen"
    if scenario == DEMO_NIGHT_SYNCOPE:
        if t_s < NIGHT_GETUP_S:
            return "sitting"
        if t_s < NIGHT_CRUMPLE_S:
            return "stand"
        if t_s < NIGHT_CRUMPLE_S + 0.5:
            return "falling"
        return "fallen"
    if scenario == DEMO_TONIC_CLONIC:
        if t_s < TONIC_DROP_S:
            return "stand"
        if t_s < TONIC_DROP_S + 0.4:
            return "falling"
        return "fallen"
    if scenario == DEMO_SILENT_SLUMP:
        return "sitting" if t_s < SLUMP_S + 0.5 else "fallen"
    return "stand"


class MockSensorClient:
    """Synthesise telemetry without any hardware.

    Default behaviour: resting baseline (HR ~72 BPM, gravity-dominant
    accelerometer). The scenario can be scripted via the ``scenario``
    argument. Respects ``WristbandConfig.has_accelerometer`` so that
    HR-only operation mirrors current hardware status (no IMU yet).
    """

    SCENARIOS = MOCK_SCENARIOS

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

    @property
    def connected(self) -> bool:
        """Mock link is up for the whole run (synthetic telemetry)."""
        return not self._stop.is_set()

    async def run(self) -> None:
        log.info(
            "MockSensorClient: scenario=%s accel=%s hr=%.2fHz",
            self.scenario,
            f"{self.accel_hz}Hz" if self.cfg.has_accelerometer else "DISABLED (no IMU)",
            self.hr_hz,
        )
        t0_ms = now_ms()
        if self.scenario in DEMO_PLAYBOOKS:
            log.info("Demo %s: %s", self.scenario, DEMO_NARRATION[self.scenario])
        elif self.scenario != "resting":
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
        if self.scenario in DEMO_PLAYBOOKS:
            return demo_accel(self.scenario, t_s, noise())
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
        if self.scenario in DEMO_PLAYBOOKS:
            return demo_hr(self.scenario, t_s, jitter)
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
