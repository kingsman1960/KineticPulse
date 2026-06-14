"""Async fusion engine.

Consumes:
- Detection events from the vision stage (best per-frame detection).
- Pose-feature snapshots from the pose stage.
- Sensor events from the BLE / mock client.

Produces a :class:`TierDecision` whenever the running picture crosses a
threshold. The engine itself does not send webhooks or open WebRTC; it
emits :class:`FusionSnapshot` objects to a downstream queue.
"""

from __future__ import annotations

import asyncio
import collections
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Sequence

from kineticpulse.config import RuntimeConfig
from kineticpulse.fusion.rules import (
    AccelSignature,
    HrAggregate,
    HrSignature,
    PoseSignature,
    accel_signature,
    aggregate_hr,
    hr_signature,
    pose_signature,
)
from kineticpulse.fusion.tiers import EmergencyTier, TierDecision, classify
from kineticpulse.sensors.parser import (
    AccelSample,
    HrSample,
    PulseLost,
    SensorEvent,
)
from kineticpulse.temporal.types import ActionLogits
from kineticpulse.utils.logging import get_logger
from kineticpulse.utils.timing import now_ms
from kineticpulse.vision.detector import Detection
from kineticpulse.vision.features import PoseFeatures

log = get_logger(__name__)


@dataclass
class FusionSnapshot:
    """A single fusion-engine decision plus the inputs that produced it."""

    decision: TierDecision
    pose: PoseSignature
    accel: AccelSignature
    hr: HrSignature
    latest_hr_bpm: Optional[int]
    latest_accel_g: Optional[float]
    detector_class: Optional[str]
    detector_conf: Optional[float]
    action_class: Optional[str] = None       # stable label if hysteresis settled, else raw argmax
    action_conf: Optional[float] = None      # smoothed probability of `action_class`
    timestamp_ms: int = field(default_factory=now_ms)


class FusionEngine:
    """Time-windowed sensor fusion."""

    def __init__(
        self,
        cfg: RuntimeConfig,
        detections: "asyncio.Queue[Detection]",
        features: "asyncio.Queue[PoseFeatures]",
        sensor_events: "asyncio.Queue[SensorEvent]",
        snapshots: "asyncio.Queue[FusionSnapshot]",
        actions: "Optional[asyncio.Queue[ActionLogits]]" = None,
        window_ms: int = 2000,
        evaluate_every_ms: int = 150,
    ) -> None:
        self.cfg = cfg
        self.detections = detections
        self.features = features
        self.sensor_events = sensor_events
        self.snapshots = snapshots
        self.actions = actions
        self.window_ms = window_ms
        self.evaluate_every_ms = evaluate_every_ms

        self._accel: Deque[AccelSample] = collections.deque(maxlen=400)   # ~8 s at 50 Hz
        self._hr_events: Deque[SensorEvent] = collections.deque(maxlen=64)
        self._last_detection: Optional[Detection] = None
        self._last_features: Optional[PoseFeatures] = None
        self._last_action: Optional[ActionLogits] = None
        self._last_decision: Optional[TierDecision] = None
        self._stop = asyncio.Event()

    # ----- ingest tasks -------------------------------------------------- #

    async def _ingest_detections(self) -> None:
        while not self._stop.is_set():
            det = await self.detections.get()
            self._last_detection = det

    async def _ingest_features(self) -> None:
        while not self._stop.is_set():
            feat = await self.features.get()
            self._last_features = feat

    async def _ingest_sensors(self) -> None:
        while not self._stop.is_set():
            ev = await self.sensor_events.get()
            if isinstance(ev, AccelSample):
                self._accel.append(ev)
            elif isinstance(ev, (HrSample, PulseLost)):
                self._hr_events.append(ev)

    async def _ingest_actions(self) -> None:
        if self.actions is None:
            return
        while not self._stop.is_set():
            ev = await self.actions.get()
            self._last_action = ev

    # ----- evaluation loop ---------------------------------------------- #

    def _accel_window(self, now: int) -> Sequence[AccelSample]:
        cutoff = now - self.window_ms
        return [s for s in self._accel if s.timestamp_ms >= cutoff]

    def _hr_window(self, now: int) -> Sequence[SensorEvent]:
        cutoff = now - 5 * self.window_ms
        return [e for e in self._hr_events if e.timestamp_ms >= cutoff]

    def _build_snapshot(self) -> FusionSnapshot:
        ts = now_ms()
        det = self._last_detection
        feat = self._last_features
        action = self._last_action

        action_threshold = float(
            getattr(self.cfg.temporal, "action_confidence_threshold", 0.55)
        )
        pose_sig = pose_signature(
            detector_class=det.cls.value if det else None,
            torso_angle_deg=feat.torso_angle_deg if feat else None,
            aspect_ratio=feat.aspect_ratio if feat else None,
            centroid_vel_pps=feat.centroid_vel_pps if feat else None,
            action_logits=action,
            action_confidence_threshold=action_threshold,
        )
        accel_win = self._accel_window(ts)
        accel_sig = accel_signature(accel_win, self.cfg.thresholds)
        hr_win = self._hr_window(ts)
        hr_agg = aggregate_hr(hr_win, ts)
        hr_sig = hr_signature(hr_agg, self.cfg.thresholds)

        decision = classify(pose_sig, accel_sig, hr_sig)
        latest_accel_g = accel_win[-1].magnitude_g if accel_win else None

        if action is not None:
            published_label = action.stable_label or action.argmax_label
            published_conf = action.confidence_of(published_label)
        else:
            published_label = None
            published_conf = None

        return FusionSnapshot(
            decision=decision,
            pose=pose_sig,
            accel=accel_sig,
            hr=hr_sig,
            latest_hr_bpm=hr_agg.latest_bpm,
            latest_accel_g=latest_accel_g,
            detector_class=det.cls.value if det else None,
            detector_conf=det.confidence if det else None,
            action_class=published_label,
            action_conf=published_conf,
            timestamp_ms=ts,
        )

    async def _evaluate_loop(self) -> None:
        interval_s = self.evaluate_every_ms / 1000.0
        while not self._stop.is_set():
            await asyncio.sleep(interval_s)
            snap = self._build_snapshot()
            prev = self._last_decision
            changed = prev is None or prev.tier != snap.decision.tier
            if changed and snap.decision.tier != EmergencyTier.NONE:
                log.info("Fusion: tier=%s scenario=%s reason=%s",
                         snap.decision.tier.value, snap.decision.scenario,
                         snap.decision.reason)
            self._last_decision = snap.decision
            try:
                self.snapshots.put_nowait(snap)
            except asyncio.QueueFull:
                try:
                    _ = self.snapshots.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                self.snapshots.put_nowait(snap)

    async def run(self) -> None:
        await asyncio.gather(
            self._ingest_detections(),
            self._ingest_features(),
            self._ingest_sensors(),
            self._ingest_actions(),
            self._evaluate_loop(),
        )

    def stop(self) -> None:
        self._stop.set()
