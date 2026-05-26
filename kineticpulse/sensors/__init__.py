"""Wearable sensor inputs (TCP wristband, with BLE as fallback)."""

from __future__ import annotations

import asyncio
from typing import Protocol

from kineticpulse.config import WristbandConfig
from kineticpulse.sensors.ble import BleClient
from kineticpulse.sensors.mock import MockBleClient, MockSensorClient
from kineticpulse.sensors.parser import (
    AccelSample,
    HrSample,
    PulseLost,
    SensorEvent,
    parse_accel_packet,
    parse_hr_packet,
)
from kineticpulse.sensors.ppg import PpgProcessor, PpgSample, parse_ppg_packet
from kineticpulse.sensors.tcp import TcpSensorServer
from kineticpulse.utils.logging import get_logger

log = get_logger(__name__)


class _SensorClient(Protocol):
    async def run(self) -> None: ...
    def stop(self) -> None: ...


def build_sensor_client(
    cfg: WristbandConfig,
    events: "asyncio.Queue[SensorEvent]",
    *,
    mock: bool = False,
    scenario: str = "resting",
) -> _SensorClient:
    """Pick the right sensor client based on ``cfg.transport``.

    The ``mock`` flag short-circuits everything: it returns a
    :class:`MockSensorClient` regardless of transport so the rest of
    the pipeline can be exercised end-to-end without any hardware.
    """
    if mock:
        return MockSensorClient(cfg, events, scenario=scenario)

    transport = (cfg.transport or "tcp").strip().lower()
    if transport == "tcp":
        return TcpSensorServer(cfg, events)
    if transport == "ble":
        if not cfg.mac:
            log.warning(
                "wristband.transport=ble but wristband.mac is not set; "
                "falling back to the mock sensor client."
            )
            return MockSensorClient(cfg, events, scenario=scenario)
        return BleClient(cfg, events)
    raise ValueError(
        f"Unknown wristband.transport: {cfg.transport!r}. "
        f"Expected one of: 'tcp', 'ble'."
    )


# Back-compat shim: existing code / scripts that imported build_ble_client
# keep working. New code should call build_sensor_client.
def build_ble_client(
    cfg: WristbandConfig,
    events: "asyncio.Queue[SensorEvent]",
    *,
    mock: bool = False,
    scenario: str = "resting",
) -> _SensorClient:
    """Deprecated alias for :func:`build_sensor_client`."""
    return build_sensor_client(cfg, events, mock=mock, scenario=scenario)


__all__ = [
    "AccelSample",
    "HrSample",
    "PulseLost",
    "SensorEvent",
    "parse_accel_packet",
    "parse_hr_packet",
    "parse_ppg_packet",
    "PpgSample",
    "PpgProcessor",
    "BleClient",
    "TcpSensorServer",
    "MockSensorClient",
    "MockBleClient",          # back-compat alias
    "build_sensor_client",
    "build_ble_client",       # back-compat alias
]
