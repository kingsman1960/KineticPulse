"""BLE telemetry client for the KineticPulse wristband (legacy / fallback).

The wristband moved from BLE to TCP/Wi-Fi for stability - see
:mod:`kineticpulse.sensors.tcp` for the primary path. This module is
kept so future BLE wearables (or a fallback during Wi-Fi outages) can
flip ``wristband.transport: ble`` in the config and run without code
changes.

:class:`BleClient` uses ``bleak`` to talk to a real wristband (PRD
section 4 requires auto-reconnect; this client retries on disconnect
with exponential backoff up to ``reconnect_delay_s``). The synthetic
generator that used to live in this file as ``MockBleClient`` moved to
:mod:`kineticpulse.sensors.mock` and was renamed
``MockSensorClient`` (a back-compat alias is still exported there).

Hardware-capability flags
-------------------------

The two ``WristbandConfig`` flags decide which subscriptions the client
sets up:

* ``has_accelerometer`` - when ``False`` (current build status) the
  client skips the IMU subscription entirely. The fusion engine already
  returns ``AccelSignature.UNKNOWN`` in that case and degrades
  gracefully (see
  ``tests/test_fusion_rules.py::test_no_accel_seizure_degrades_to_tier_1``).
* ``has_ppg_raw`` - when ``True`` (current direction with MAX30102 +
  ESP32) the client subscribes to the raw-PPG characteristic and routes
  every received packet through
  :class:`~kineticpulse.sensors.ppg.PpgProcessor`, which produces
  :class:`HrSample` events. When ``False`` the client subscribes to the
  Bluetooth SIG standard Heart Rate Measurement characteristic
  (``0x2A37``).
"""

from __future__ import annotations

import asyncio

from kineticpulse.config import WristbandConfig
from kineticpulse.sensors.parser import (
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
        self._ppg_processor = None
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
