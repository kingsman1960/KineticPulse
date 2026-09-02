"""KineticPulse Pipeline 2 entry point.

Wires together capture, detector, pose, features, sensors, voice, fusion,
alerts, and WebRTC. Run with:

    python -m kineticpulse.main --config config.yaml
    python -m kineticpulse.main --config config.yaml --mock-ble --mock-stt

The orchestrator uses :mod:`asyncio` for I/O-bound stages and a thread
pool for blocking inference (Ultralytics releases the GIL during forward
passes, so this is sufficient on Jetson Orin Nano).
"""

from __future__ import annotations

import argparse
import asyncio
import io
import signal
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from kineticpulse.alerts.payload import build_payload
from kineticpulse.alerts.webhooks import WebhookDispatcher
from kineticpulse.config import RuntimeConfig, load_config
from kineticpulse.fusion.engine import FusionEngine, FusionSnapshot
from kineticpulse.fusion.tiers import EmergencyTier
from kineticpulse.monitoring import MonitoringPublisher
from kineticpulse.runtime_status import CaregiverRuntimeStatus
from kineticpulse.sensors import build_sensor_client
from kineticpulse.sensors.mock import (
    DEMO_CLI,
    DEMO_PLAYBOOKS,
    MOCK_SCENARIOS,
    demo_posture,
)
from kineticpulse.sensors.parser import SensorEvent
from kineticpulse.webrtc.session_meta import build_session_meta
from kineticpulse.temporal.stgcn import KeypointRingBuffer, TemporalHead
from kineticpulse.temporal.types import ActionLogits
from kineticpulse.utils.logging import configure_logging, get_logger
from kineticpulse.utils.timing import now_ms
from kineticpulse.vision.capture import Frame, build_source
from kineticpulse.vision.detector import Detection, FallDetector, PostureClass
from kineticpulse.vision.features import PoseFeatures, extract_features
from kineticpulse.vision.pose import PoseEstimator, PoseResult
from kineticpulse.voice.prompts import PromptPlayer
from kineticpulse.voice.safe_words import VoiceVerdict, classify_response
from kineticpulse.voice.stt import build_stt
from kineticpulse.webrtc.peer import WebrtcPeer
from kineticpulse.webrtc.types import WebrtcSessionMeta

log = get_logger("kineticpulse.main")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="KineticPulse Pipeline 2 runtime.")
    p.add_argument("--config", type=Path, required=True, help="Path to runtime config YAML.")
    p.add_argument("--mock-ble", "--mock-sensors", dest="mock_ble", action="store_true",
                   help="Use the synthetic sensor generator (no wristband required). "
                        "Bypasses both the TCP server and the BLE client. "
                        "(--mock-sensors is a clearer alias kept for the post-BLE world.)")
    p.add_argument("--mock-ble-scenario", "--mock-sensors-scenario",
                   dest="mock_ble_scenario", default="resting",
                   choices=MOCK_SCENARIOS,
                   help="Scenario for the mock sensor client.")
    p.add_argument("--demo", metavar="PLAYBOOK", default=None, choices=tuple(DEMO_CLI),
                   help="Safe dashboard playbook (implies --mock-ble --mock-stt --no-camera). "
                        "One of: " + ", ".join(DEMO_CLI) + ".")
    p.add_argument("--demo-syncope-seizure", action="store_true",
                   help="Alias for --demo syncope-seizure.")
    p.add_argument("--mock-stt", action="store_true",
                   help="Use a canned STT response instead of a real microphone.")
    p.add_argument("--mock-stt-response", default="",
                   help="Canned utterance returned by --mock-stt (default: empty = silence).")
    p.add_argument("--no-camera", action="store_true",
                   help="Skip camera + detector (telemetry-only smoke test).")
    p.add_argument("--max-runtime-s", type=float, default=None,
                   help="Stop the orchestrator after this many seconds (smoke-test / CI).")
    args = p.parse_args()
    if args.demo_syncope_seizure and args.demo is None:
        args.demo = "syncope-seizure"
    if args.demo:
        args.mock_ble = True
        args.mock_stt = True
        args.no_camera = True
        args.mock_ble_scenario = DEMO_CLI[args.demo]
    return args


# --------------------------------------------------------------------------- #
# Vision worker
# --------------------------------------------------------------------------- #


_POSTURE = {
    "stand": PostureClass.STAND,
    "sitting": PostureClass.SITTING,
    "falling": PostureClass.FALLING,
    "fallen": PostureClass.FALLEN,
}


async def _script_demo_posture(
    detections_q: "asyncio.Queue[Detection]",
    stop: asyncio.Event,
    scenario: str,
) -> None:
    """Script detector class from the playbook — no camera, no real person."""
    log.info("Demo vision: scenario=%s", scenario)
    t0 = now_ms()
    while not stop.is_set():
        label = demo_posture(scenario, (now_ms() - t0) / 1000.0)
        fallen = label == "fallen"
        det = Detection(
            bbox_xyxy=(140.0, 220.0, 520.0, 680.0),
            cls=_POSTURE.get(label, PostureClass.STAND),
            confidence=0.91 if fallen else 0.88,
            timestamp_ms=now_ms(),
        )
        try:
            detections_q.put_nowait(det)
        except asyncio.QueueFull:
            try:
                detections_q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            detections_q.put_nowait(det)
        await asyncio.sleep(0.2)


async def _vision_worker(
    cfg: RuntimeConfig,
    detector: Optional[FallDetector],
    pose: Optional[PoseEstimator],
    detections_q: "asyncio.Queue[Detection]",
    features_q: "asyncio.Queue[PoseFeatures]",
    actions_q: "asyncio.Queue[ActionLogits]",
    stop: asyncio.Event,
    no_camera: bool,
    scenario: str = "resting",
) -> None:
    if no_camera:
        if scenario in DEMO_PLAYBOOKS:
            await _script_demo_posture(detections_q, stop, scenario)
        else:
            log.info("--no-camera set; skipping capture loop.")
            await stop.wait()
        return

    source = build_source(cfg.camera)
    source.start()
    log.info("Capture started: source=%s device=%s", cfg.camera.source, cfg.camera.device)

    keypoint_buffer = KeypointRingBuffer(maxlen=cfg.temporal.window_size)
    temporal_head = TemporalHead(cfg.temporal)
    prev_pose: Optional[PoseResult] = None
    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="vision")

    try:
        while not stop.is_set():
            frame: Optional[Frame] = await loop.run_in_executor(
                None, lambda: source.queue.get(timeout=1.0)
            )
            if frame is None:
                continue

            det_future = loop.run_in_executor(
                executor, detector.infer, frame.image, frame.timestamp_ms
            ) if detector is not None else None
            pose_future = loop.run_in_executor(
                executor, pose.infer, frame.image, frame.timestamp_ms
            ) if pose is not None else None

            detections = await det_future if det_future is not None else []
            poses = await pose_future if pose_future is not None else []

            best_det = FallDetector.best_person(detections) if detections else None
            best_pose = PoseEstimator.best_person(poses) if poses else None

            if best_det is not None:
                try:
                    detections_q.put_nowait(best_det)
                except asyncio.QueueFull:
                    pass

            keypoint_buffer.push(best_pose.keypoints if best_pose else None)
            features = extract_features(
                pose=best_pose,
                prev_pose=prev_pose,
                history=keypoint_buffer.snapshot(),
                timestamp_ms=frame.timestamp_ms,
            )
            prev_pose = best_pose if best_pose is not None else prev_pose
            try:
                features_q.put_nowait(features)
            except asyncio.QueueFull:
                pass

            action = temporal_head.maybe_predict(
                keypoint_buffer, features, frame.timestamp_ms,
            )
            if action is not None:
                try:
                    actions_q.put_nowait(action)
                except asyncio.QueueFull:
                    # Drop the oldest queued action so the engine stays
                    # near-real-time. The temporal head runs on a stride
                    # so dropped frames are safe.
                    try:
                        _ = actions_q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    try:
                        actions_q.put_nowait(action)
                    except asyncio.QueueFull:
                        pass
    finally:
        source.stop()
        executor.shutdown(wait=False)


# --------------------------------------------------------------------------- #
# Verification / dispatch worker
# --------------------------------------------------------------------------- #


async def _cancel(task: asyncio.Task) -> None:
    """Cancel a task and swallow whatever it raises on the way out."""
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


async def _dispatch_worker(
    cfg: RuntimeConfig,
    snapshots_q: "asyncio.Queue[FusionSnapshot]",
    args: argparse.Namespace,
    stop: asyncio.Event,
    runtime_status: CaregiverRuntimeStatus,
) -> None:
    dispatcher = WebhookDispatcher(cfg.alerts.webhooks)
    prompt_player = PromptPlayer()
    stt = build_stt(cfg.voice, mock=args.mock_stt, mock_response=args.mock_stt_response)
    webrtc = WebrtcPeer(
        cfg.webrtc,
        camera_cfg=cfg.camera,
        subject_id=cfg.alerts.subject_id,
        location=cfg.alerts.location,
    )

    cooldown_ms = 8_000           # do not retrigger Tier 1 within this window
    last_tier_at_ms = 0
    last_dispatched_tier = None

    async def _dispatch_alert(payload) -> str:
        runtime_status.set_alert("pending")
        status = await dispatcher.dispatch(payload)
        runtime_status.set_alert(status)
        session_id = (payload.session or {}).get("id", "")
        runtime_status.push_event(
            severity="critical" if status == "failed" else "warning",
            category="alert",
            title=f"Alert dispatch {status}",
            detail=f"tier={payload.tier} session={session_id}",
            timestamp_ms=payload.timestamp_ms,
        )
        return status

    try:
        async def _safe_webrtc_start(*, snap: FusionSnapshot, session_id: str, session_meta: WebrtcSessionMeta) -> None:
            if not cfg.webrtc.enabled:
                return
            try:
                await asyncio.wait_for(
                    webrtc.start(snap, session_id=session_id, session_meta=session_meta),
                    timeout=max(1.0, cfg.webrtc.connect_timeout_s + 1.0),
                )
            except Exception as exc:
                log.warning("WebRTC startup failed (session=%s): %s", session_id, exc)

        async def _escalate(snap: FusionSnapshot, voice_extra: Optional[dict] = None) -> None:
            """Fire webhooks and open the live feed for one confirmed emergency."""
            session_id = f"{cfg.webrtc.session_id_prefix}-{uuid.uuid4().hex[:12]}"
            payload = build_payload(
                cfg.alerts, snap, voice_extra=voice_extra, session_id=session_id
            )
            session_meta = build_session_meta(
                session_id=session_id,
                subject_id=cfg.alerts.subject_id,
                location=cfg.alerts.location,
                snapshot=snap,
                extra={"voice_verdict": voice_extra["verdict"]} if voice_extra else None,
            )
            await asyncio.gather(
                _dispatch_alert(payload),
                _safe_webrtc_start(snap=snap, session_id=session_id, session_meta=session_meta),
            )

        async def _next_voice_bypass() -> FusionSnapshot:
            """Wait for a tier that must not wait for a verbal reply.

            Snapshots that do not qualify are discarded: by the time voice
            verification finishes they are stale, and the cooldown below
            would drop them anyway.
            """
            while True:
                candidate = await snapshots_q.get()
                if candidate.decision.tier.bypasses_voice:
                    return candidate

        while not stop.is_set():
            try:
                snap: FusionSnapshot = await asyncio.wait_for(snapshots_q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            tier = snap.decision.tier
            if tier == EmergencyTier.NONE or tier == EmergencyTier.TIER_0_DISMISS:
                continue
            if tier == last_dispatched_tier:
                continue
            if not tier.bypasses_voice and last_dispatched_tier is not None and snap.timestamp_ms - last_tier_at_ms < cooldown_ms:
                continue
            last_dispatched_tier = tier
            last_tier_at_ms = snap.timestamp_ms

            log.warning("Emergency tier=%s scenario=%s reason=%s",
                        tier.value, snap.decision.scenario, snap.decision.reason)
            runtime_status.push_event(
                severity="critical" if tier.bypasses_voice else "warning",
                category="fusion",
                title=f"Emergency {tier.value}",
                detail=snap.decision.reason,
                timestamp_ms=snap.timestamp_ms,
            )

            if tier.bypasses_voice:
                runtime_status.set_voice("not_required")
                await _escalate(snap)
                continue

            # Tier 1: voice verification.
            if not cfg.voice.enabled:
                log.info("Voice verification disabled; escalating Tier 1 unverified.")
                runtime_status.set_voice("not_required")
                await _escalate(snap)
                continue

            runtime_status.set_voice("pending")
            runtime_status.push_event(
                severity="info",
                category="voice",
                title="Voice verification started",
                detail=cfg.voice.prompt_text,
                timestamp_ms=snap.timestamp_ms,
            )
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, prompt_player.say, cfg.voice.prompt_text)

            # PRD: critical vitals during verification override the verbal
            # reply. Race the transcript against the fusion queue rather than
            # blocking on STT for the whole verify window.
            listening = asyncio.create_task(
                stt.listen_once(duration_s=cfg.voice.verify_timeout_s)
            )
            watching = asyncio.create_task(_next_voice_bypass())
            done, _pending = await asyncio.wait(
                {listening, watching}, return_when=asyncio.FIRST_COMPLETED
            )

            if watching in done:
                critical = watching.result()
                await _cancel(listening)
                log.warning("Vitals critical during verification (%s); overriding voice.",
                            critical.decision.reason)
                runtime_status.set_voice("not_required")
                runtime_status.push_event(
                    severity="critical",
                    category="voice",
                    title="Voice verification overridden",
                    detail=critical.decision.reason,
                    timestamp_ms=critical.timestamp_ms,
                )
                last_dispatched_tier = critical.decision.tier
                last_tier_at_ms = critical.timestamp_ms
                await _escalate(critical)
                continue

            await _cancel(watching)
            try:
                transcript = listening.result().text
            except Exception as exc:
                # A missing microphone must not take the alert path down with
                # it; no transcript is treated the same as silence.
                log.warning("STT unavailable (%s); treating as no response.", exc)
                transcript = ""

            verdict, matched = classify_response(
                text=transcript,
                safe_words=cfg.voice.safe_words,
                distress_words=cfg.voice.distress_words,
            )
            log.info("STT: text=%r verdict=%s matched=%r",
                     transcript, verdict.value, matched)
            runtime_status.set_voice(verdict.value)
            runtime_status.push_event(
                severity="info" if verdict == VoiceVerdict.SAFE else "warning",
                category="voice",
                title=f"Voice verdict: {verdict.value}",
                detail=transcript or "(silence / no transcript)",
                timestamp_ms=snap.timestamp_ms,
            )

            if verdict == VoiceVerdict.SAFE:
                log.info("Subject confirmed safe; alert canceled.")
                runtime_status.set_alert("idle")
                continue

            await _escalate(snap, voice_extra={
                "transcript": transcript,
                "verdict": verdict.value,
                "matched_phrase": matched,
            })
    finally:
        await dispatcher.aclose()
        await webrtc.stop()


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


async def run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    configure_logging(level=cfg.logging.level, json_format=cfg.logging.json)
    log.info("KineticPulse starting (config=%s, mock_ble=%s, mock_stt=%s, no_camera=%s)",
             args.config, args.mock_ble, args.mock_stt, args.no_camera)

    if args.mock_ble_scenario in DEMO_PLAYBOOKS and not cfg.wristband.has_accelerometer:
        log.warning("Demo needs IMU samples; forcing wristband.has_accelerometer=true")
        cfg.wristband.has_accelerometer = True

    detections_q: "asyncio.Queue[Detection]" = asyncio.Queue(maxsize=8)
    features_q: "asyncio.Queue[PoseFeatures]" = asyncio.Queue(maxsize=8)
    actions_q: "asyncio.Queue[ActionLogits]" = asyncio.Queue(maxsize=8)
    sensor_q: "asyncio.Queue[SensorEvent]" = asyncio.Queue(maxsize=512)
    snapshots_q: "asyncio.Queue[FusionSnapshot]" = asyncio.Queue(maxsize=16)
    stop = asyncio.Event()

    detector = None
    pose = None
    if not args.no_camera:
        try:
            detector = FallDetector(cfg.detector)
            detector.load()
        except FileNotFoundError as exc:
            log.warning("%s -- continuing without trained detector.", exc)
            detector = None
        try:
            pose = PoseEstimator(cfg.pose)
            pose.load()
        except Exception as exc:
            log.warning("Pose model unavailable: %s", exc)
            pose = None

    # Sensor source: TCP server is the production path now; BLE is a fallback
    # behind cfg.wristband.transport. The factory transparently degrades to
    # the synthetic generator when --mock-ble is set or when transport=ble
    # is selected without a configured MAC.
    sensors = build_sensor_client(
        cfg.wristband, sensor_q,
        mock=args.mock_ble,
        scenario=args.mock_ble_scenario,
    )
    fusion = FusionEngine(
        cfg=cfg,
        detections=detections_q,
        features=features_q,
        sensor_events=sensor_q,
        snapshots=snapshots_q,
        actions=actions_q,
    )

    loop = asyncio.get_event_loop()
    if hasattr(signal, "SIGINT"):
        try:
            loop.add_signal_handler(signal.SIGINT, stop.set)
            loop.add_signal_handler(signal.SIGTERM, stop.set)
        except NotImplementedError:
            pass

    runtime_status = CaregiverRuntimeStatus()
    monitoring: Optional[MonitoringPublisher] = None
    if cfg.monitoring.enabled:
        monitoring = MonitoringPublisher(
            host=cfg.monitoring.host,
            port=cfg.monitoring.port,
            alerts=cfg.alerts,
            latest_snapshot=lambda: fusion.latest,
            sensors=sensors,
            runtime_status=runtime_status,
        )

    tasks = [
        asyncio.create_task(sensors.run(), name="sensors"),
        asyncio.create_task(fusion.run(), name="fusion"),
        asyncio.create_task(_vision_worker(
            cfg, detector, pose, detections_q, features_q, actions_q, stop,
            args.no_camera, args.mock_ble_scenario,
        ), name="vision"),
        asyncio.create_task(
            _dispatch_worker(cfg, snapshots_q, args, stop, runtime_status),
            name="dispatch",
        ),
    ]
    if monitoring is not None:
        tasks.append(asyncio.create_task(monitoring.run(), name="monitoring"))

    sentinels = [asyncio.create_task(stop.wait(), name="stop")]
    if args.max_runtime_s is not None and args.max_runtime_s > 0:
        async def _deadline() -> None:
            await asyncio.sleep(args.max_runtime_s)
            log.info("--max-runtime-s reached; stopping.")
            stop.set()
        sentinels.append(asyncio.create_task(_deadline(), name="deadline"))

    done, pending = await asyncio.wait(
        tasks + sentinels,
        return_when=asyncio.FIRST_COMPLETED,
    )
    stop.set()
    sensors.stop()
    fusion.stop()
    if monitoring is not None:
        monitoring.stop()
    for t in pending:
        t.cancel()
    for t in pending:
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
    log.info("KineticPulse stopped.")
    return 0


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
