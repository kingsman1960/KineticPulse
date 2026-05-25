"""BLE telemetry client for the KineticPulse wristband.

Two implementations:

* :class:`BleClient` uses ``bleak`` to talk to a real wristband (PRD
  section 4 requires auto-reconnect; this client retries on disconnect
  with exponential backoff up to ``reconnect_delay_s``).
* :class:`MockBleClient` emits a synthetic stream (resting baseline plus
  scripted fall scenarios) so the rest of the pipeline can be developed
  without hardware. Enabled via the ``--mock-ble`` CLI flag.

Hardware-capability flags
-------------------------

The two ``WristbandConfig`` flags decide which subscriptions the client
sets up:

* ``has_accelerometer`` - when ``False`` (current build status) the
  client skips the IMU subscription entirely; the mock generator emits
  no accel samples either. The fusion engine already returns
  ``AccelSignature.UNKNOWN`` in that case and degrades gracefully (see
  ``tests/test_fusion_rules.py::test_no_accel_seizure_degrades_to_tier_1``).
* ``has_ppg_raw`` - when ``True`` (current direction with MAX30102 +
  ESP32) the client subscribes to the raw-PPG characteristic and routes
  every received packet through :class:`~kineticpulse.sensors.ppg.PpgProcessor`,
  which produces :class:`HrSample` events. When ``False`` the client
  subscribes to the Bluetooth SIG standard Heart Rate Measurement
  characteristic (``0x2A37``).
"""

from __future__ import annotations

import asyncio
import math
import random
from typing import Optional

from kineticpulse.config import WristbandConfig
from kineticpulse.sensors.parser import (
    AccelSample,
    HrSample,
    PulseLost,
    SensorEvent,
    parse_accel_packet,
    parse_hr_packet,
)
from kineticpulse.sensors.ppg import PpgProcessor, parse_ppg_packet
from kineticpulse.utils.logging import get_logger
from kineticpulse.utils.timing import now_ms

log = get_logger(__name__)


# Default UUIDs (overridable via WristbandConfig). The HR UUID matches
# the Bluetooth SIG standard so any compliant heart-rate monitor works
# as a stand-in for the custom wristband during bring-up. The PPG and
# accel UUIDs are vendor placeholders - replace once the ESP32 firmware
# locks them in.
DEFAULT_HR_CHARACTERISTIC = "00002a37-0000-1000-8000-00805f9b34fb"
DEFAULT_ACCEL_CHARACTERISTIC = "0000ff01-0000-1000-8000-00805f9b34fb"
DEFAULT_PPG_CHARACTERISTIC = "0000ff02-0000-1000-8000-00805f9b34fb"


class BleClient:
    """Real BLE client backed by `bleak`."""

    def __init__(self, cfg: WristbandConfig, events: "asyncio.Queue[SensorEvent]") -> None:
        self.cfg = cfg
        self.events = events
        self._stop = asyncio.Event()
        self._ppg_processor: Optional[PpgProcessor] = None
        if cfg.has_ppg_raw:
            self._ppg_processor = PpgProcessor(sample_rate_hz=cfg.ppg_sample_rate_hz)

    async def run(self) -> None:
        try:
            from bleak import BleakClient
        except ImportError as exc:
            raise ImportError(
                "bleak is required for the real BLE client. "
                "Install with `pip install -r requirements.txt`, or use --mock-ble."
            ) from exc

        if not self.cfg.mac:
            raise ValueError(
                "wristband.mac is not set in config. "
                "Set it to your wristband's BLE MAC or run with --mock-ble."
            )

        hr_uuid = self.cfg.hr_service_uuid or DEFAULT_HR_CHARACTERISTIC
        accel_uuid = self.cfg.accel_service_uuid or DEFAULT_ACCEL_CHARACTERISTIC
        ppg_uuid = self.cfg.ppg_service_uuid or DEFAULT_PPG_CHARACTERISTIC
        delay = self.cfg.reconnect_delay_s
        backoff = delay

        log.info(
            "BLE: capability flags has_accelerometer=%s has_ppg_raw=%s",
            self.cfg.has_accelerometer, self.cfg.has_ppg_raw,
        )

        while not self._stop.is_set():
            try:
                log.info("BLE: connecting to %s", self.cfg.mac)
                async with BleakClient(self.cfg.mac) as client:
                    log.info("BLE: connected, subscribing to notifications")
                    backoff = delay

                    if self.cfg.has_accelerometer:
                        def _on_accel(_handle, data: bytearray) -> None:
                            sample = parse_accel_packet(bytes(data), now_ms())
                            if sample is not None:
                                self._submit(sample)
                        await client.start_notify(accel_uuid, _on_accel)
                    else:
                        log.info("BLE: skipping accel subscription (has_accelerometer=False).")

                    if self.cfg.has_ppg_raw and self._ppg_processor is not None:
                        def _on_ppg(_handle, data: bytearray) -> None:
                            base_ts = now_ms()
                            samples = parse_ppg_packet(
                                bytes(data), base_ts,
                                sample_rate_hz=self.cfg.ppg_sample_rate_hz,
                            )
                            for s in samples:
                                hr = self._ppg_processor.push(s)
                                if hr is not None:
                                    self._submit(hr)
                        await client.start_notify(ppg_uuid, _on_ppg)
                        log.info("BLE: subscribed to raw PPG (%s @ %d Hz)",
                                 ppg_uuid, self.cfg.ppg_sample_rate_hz)
                    else:
                        def _on_hr(_handle, data: bytearray) -> None:
                            sample = parse_hr_packet(bytes(data), now_ms())
                            if sample is not None:
                                self._submit(sample)
                        await client.start_notify(hr_uuid, _on_hr)
                        log.info("BLE: subscribed to standard HR characteristic (%s)", hr_uuid)

                    while client.is_connected and not self._stop.is_set():
                        await asyncio.sleep(0.5)
            except Exception as exc:
                log.warning("BLE: %s; reconnecting in %.2fs", exc, backoff)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2.0, 30.0)

    def _submit(self, ev: SensorEvent) -> None:
        try:
            self.events.put_nowait(ev)
        except asyncio.QueueFull:
            try:
                _ = self.events.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self.events.put_nowait(ev)

    def stop(self) -> None:
        self._stop.set()


class MockBleClient:
    """Synthesise telemetry without hardware.

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
            "MockBleClient: scenario=%s accel=%s hr=%.2fHz",
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

    def _accel_at(self, t_s: float) -> tuple:
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


def build_ble_client(
    cfg: WristbandConfig,
    events: "asyncio.Queue[SensorEvent]",
    *,
    mock: bool = False,
    scenario: str = "resting",
):
    """Factory: pick real or mock BLE client based on flag."""
    if mock or not cfg.mac:
        return MockBleClient(cfg, events, scenario=scenario)
    return BleClient(cfg, events)
