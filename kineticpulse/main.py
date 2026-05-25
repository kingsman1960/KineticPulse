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
from kineticpulse.sensors.ble import build_ble_client
from kineticpulse.sensors.parser import SensorEvent
from kineticpulse.temporal.stgcn import KeypointRingBuffer, TemporalHead
from kineticpulse.utils.logging import configure_logging, get_logger
from kineticpulse.utils.timing import now_ms
from kineticpulse.vision.capture import Frame, build_source
from kineticpulse.vision.detector import Detection, FallDetector
from kineticpulse.vision.features import PoseFeatures, extract_features
from kineticpulse.vision.pose import PoseEstimator, PoseResult
from kineticpulse.voice.prompts import PromptPlayer
from kineticpulse.voice.safe_words import VoiceVerdict, classify_response
from kineticpulse.voice.stt import build_stt
from kineticpulse.webrtc.peer import WebrtcPeer

log = get_logger("kineticpulse.main")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="KineticPulse Pipeline 2 runtime.")
    p.add_argument("--config", type=Path, required=True, help="Path to runtime config YAML.")
    p.add_argument("--mock-ble", action="store_true",
                   help="Use the synthetic BLE telemetry generator (no wristband required).")
    p.add_argument("--mock-ble-scenario", default="resting",
                   choices=("resting", "fall_a_standard", "fall_b_seizure", "fall_c_syncope"),
                   help="Scenario for the mock BLE client.")
    p.add_argument("--mock-stt", action="store_true",
                   help="Use a canned STT response instead of a real microphone.")
    p.add_argument("--mock-stt-response", default="",
                   help="Canned utterance returned by --mock-stt (default: empty = silence).")
    p.add_argument("--no-camera", action="store_true",
                   help="Skip camera + detector (telemetry-only smoke test).")
    return p.parse_args()


# --------------------------------------------------------------------------- #
# Vision worker
# --------------------------------------------------------------------------- #


async def _vision_worker(
    cfg: RuntimeConfig,
    detector: Optional[FallDetector],
    pose: Optional[PoseEstimator],
    detections_q: "asyncio.Queue[Detection]",
    features_q: "asyncio.Queue[PoseFeatures]",
    stop: asyncio.Event,
    no_camera: bool,
) -> None:
    if no_camera:
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

            _ = temporal_head.maybe_predict(keypoint_buffer, features, frame.timestamp_ms)
    finally:
        source.stop()
        executor.shutdown(wait=False)


# --------------------------------------------------------------------------- #
# Verification / dispatch worker
# --------------------------------------------------------------------------- #


async def _dispatch_worker(
    cfg: RuntimeConfig,
    snapshots_q: "asyncio.Queue[FusionSnapshot]",
    args: argparse.Namespace,
    stop: asyncio.Event,
) -> None:
    dispatcher = WebhookDispatcher(cfg.alerts.webhooks)
    prompt_player = PromptPlayer()
    stt = build_stt(cfg.voice, mock=args.mock_stt, mock_response=args.mock_stt_response)
    webrtc = WebrtcPeer(cfg.webrtc)

    cooldown_ms = 8_000           # do not retrigger Tier 1 within this window
    last_tier_at_ms = 0

    try:
        while not stop.is_set():
            try:
                snap: FusionSnapshot = await asyncio.wait_for(snapshots_q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            tier = snap.decision.tier
            if tier == EmergencyTier.NONE or tier == EmergencyTier.TIER_0_DISMISS:
                continue
            if snap.timestamp_ms - last_tier_at_ms < cooldown_ms:
                continue
            last_tier_at_ms = snap.timestamp_ms

            log.warning("Emergency tier=%s scenario=%s reason=%s",
                        tier.value, snap.decision.scenario, snap.decision.reason)

            if tier.bypasses_voice:
                payload = build_payload(cfg.alerts, snap)
                await asyncio.gather(
                    dispatcher.dispatch(payload),
                    webrtc.start(snap),
                )
                continue

            # Tier 1: voice verification.
            prompt_player.say(cfg.voice.prompt_text)
            result = await stt.listen_once(duration_s=cfg.voice.verify_timeout_s)
            verdict, matched = classify_response(
                text=result.text,
                safe_words=cfg.voice.safe_words,
                distress_words=cfg.voice.distress_words,
            )
            log.info("STT: text=%r verdict=%s matched=%r",
                     result.text, verdict.value, matched)

            if verdict == VoiceVerdict.SAFE:
                log.info("Subject confirmed safe; alert canceled.")
                continue

            voice_extra = {
                "transcript": result.text,
                "verdict": verdict.value,
                "matched_phrase": matched,
            }
            payload = build_payload(cfg.alerts, snap, voice_extra=voice_extra)
            await asyncio.gather(
                dispatcher.dispatch(payload),
                webrtc.start(snap),
            )
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

    detections_q: "asyncio.Queue[Detection]" = asyncio.Queue(maxsize=8)
    features_q: "asyncio.Queue[PoseFeatures]" = asyncio.Queue(maxsize=8)
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

    ble = build_ble_client(
        cfg.wristband, sensor_q,
        mock=args.mock_ble or cfg.wristband.mac is None,
        scenario=args.mock_ble_scenario,
    )
    fusion = FusionEngine(
        cfg=cfg,
        detections=detections_q,
        features=features_q,
        sensor_events=sensor_q,
        snapshots=snapshots_q,
    )

    loop = asyncio.get_event_loop()
    if hasattr(signal, "SIGINT"):
        try:
            loop.add_signal_handler(signal.SIGINT, stop.set)
            loop.add_signal_handler(signal.SIGTERM, stop.set)
        except NotImplementedError:
            pass

    tasks = [
        asyncio.create_task(ble.run(), name="ble"),
        asyncio.create_task(fusion.run(), name="fusion"),
        asyncio.create_task(_vision_worker(
            cfg, detector, pose, detections_q, features_q, stop, args.no_camera,
        ), name="vision"),
        asyncio.create_task(_dispatch_worker(cfg, snapshots_q, args, stop), name="dispatch"),
    ]

    done, pending = await asyncio.wait(
        tasks + [asyncio.create_task(stop.wait(), name="stop")],
        return_when=asyncio.FIRST_COMPLETED,
    )
    stop.set()
    ble.stop()
    fusion.stop()
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
