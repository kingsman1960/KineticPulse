# KineticPulse

**Edge-AI Fall Detection & Intelligent Emergency Response System**

KineticPulse is a multi-modal fall detection platform that runs on the **Nvidia Jetson Orin Nano** at the network edge. It fuses **Computer Vision** (a YOLOv8 fall-posture detector trained on a unified 4-class dataset: `fallen`, `falling`, `stand`, `sitting`), a **wearable wristband** (accelerometer + heart rate), and **interactive voice verification** to detect falls with high accuracy, classify the medical context (trauma, seizure, syncope, false positive), and escalate emergencies through **WebRTC** live feeds and **Webhook** alerts to caregivers and emergency services.

> Version 3.0 — Sensor Fusion Update

> **New to the codebase?** Read the [Developer Manual](docs/MANUAL.md) — repo map, module guide, data flow, cookbook recipes, testing strategy, hardware-integration milestones, and a PR checklist.

---

## Table of Contents

- [Why KineticPulse](#why-kineticpulse)
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [Hardware Components](#hardware-components)
- [Detection & Classification Logic](#detection--classification-logic)
- [Pipeline 2 Module Map](#pipeline-2-module-map)
- [Hardware Status](#hardware-status)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [Project Structure](#project-structure)
- [Non-Functional Requirements](#non-functional-requirements)
- [Roadmap](#roadmap)
- [Team & Task Assignment](#team--task-assignment)
- [Contributing](#contributing)
- [License](#license)

---

## Why KineticPulse

Vision-only fall detectors suffer from high false-positive rates (a dropped object, a person bending down, lost tracking). Wearable-only detectors miss the visual context needed to assess severity. KineticPulse combines both — plus voice interaction and vital signs — so the system can:

- **Distinguish a real fall from a dropped object** by cross-checking impact-grade accelerometer spikes against CV anomalies.
- **Classify the medical event** (standard fall vs. suspected seizure vs. cardiovascular collapse) before alerting responders.
- **Skip verbal verification** when vitals already indicate a critical emergency, saving precious seconds.
- **Open a live WebRTC channel** so caregivers can visually triage the scene in real time.

---

## Key Features

### Vision & Wearable Sensor Fusion
- Custom wristband with **Accelerometer (IMU)** and **PPG Heart Rate** sensor.
- **TCP/Wi-Fi telemetry** to the Jetson Nano (BLE was abandoned for stability — kept as a fallback transport behind a config flag).
- CV pose estimation cross-verified by impact and free-fall accelerometer signatures.
- Heart-rate context (panic spikes, dangerous drops) feeds severity classification.

### Intelligent Voice Verification
- Local Speech-to-Text status check: *"A fall has been detected. Are you okay?"*
- Escalates on:
  1. Verbal distress (e.g., *"Help"*, *"Emergency"*).
  2. Silence past a configurable timeout (default 10 s).
  3. Critical heart-rate readings during verification — overrides voice response.
- Safe-keyword false-alarm cancellation (only when vitals are stable).

### WebRTC + Webhook Alert System
- Peer-to-peer audio/video stream to the caregiver dashboard.
- Configurable webhooks: SMS, Slack, 119 / 911 APIs.
- Alert payload includes Subject ID, location, alert nature, and current vitals.

---

## System Architecture

```
+--------------------------+              +--------------------------+
|   Wearable Wristband     |  TCP / Wi-Fi  |     Jetson Nano (Edge)   |
|  (ESP32 + IMU + PPG HR)  | ──JSON lines▶ |                          |
+--------------------------+              |  ┌────────────────────┐  |
                                          |  │ CV Pose Estimation │  |
+--------------------------+              |  ├────────────────────┤  |
|   Webcam  ───────────────┼─────────────▶│  │ Sensor Fusion Core │  |
|   Mic     ───────────────┼─────────────▶│  ├────────────────────┤  |
|   Speaker ◀──────────────┼──────────────│  │ STT Voice Verifier │  |
+--------------------------+              |  └─────────┬──────────┘  |
                                          |            │             |
                                          +────────────┼─────────────+
                                                       │
                                  ┌────────────────────┼────────────────────┐
                                  ▼                                         ▼
                        +-------------------+                   +----------------------+
                        |  WebRTC Live Feed |                   |  Webhook Dispatcher  |
                        |  → Caregiver App  |                   |  SMS / Slack / 911   |
                        +-------------------+                   +----------------------+
```

### Automated Response Flow

1. **Continuous monitoring** — Jetson processes webcam frames and wristband telemetry (TCP) in parallel.
2. **Detection & sensor fusion** — flag a fall when CV detects rapid posture change **AND/OR** the accelerometer registers an impact spike.
3. **Verification** — the speaker plays the prompt; the mic begins listening.
4. **Judgment** — STT response is evaluated alongside real-time HR data.
   - *Positive response + stable vitals* → alert canceled.
   - *Negative response, silence, or critical vitals* → emergency confirmed.
5. **Action** — fire webhooks (location + vitals) and open the WebRTC channel.

---

## Hardware Components

| Component | Role |
|-----------|------|
| **Nvidia Jetson Nano** | Edge processing node (CV, STT, fusion, networking) |
| **Webcam** | Visual input for pose estimation |
| **Microphone** | Audio input for verbal verification |
| **Speaker** | Audio output for voice prompts |
| **Custom Wristband (ESP32)** | Accelerometer + PPG heart rate sensor, **TCP/Wi-Fi** link to the Jetson (BLE optional fallback) |
| **Network** | Wi-Fi / Ethernet (WebRTC, webhooks, **wristband TCP stream**); BLE retained as a fallback transport |

---

## Detection & Classification Logic

KineticPulse runs a rule-based fusion engine that classifies events into severity tiers:

### Scenario A — Standard Fall (Tier 1: Verification)
- **CV:** rapid downward translation of bounding box.
- **Accelerometer:** single high-G impact peak, then stillness.
- **Heart rate:** moderate spike (~100–120 BPM) from adrenaline.
- **Action:** trigger voice prompt and wait for STT response before escalation.

### Scenario B — Suspected Seizure (Tier 2: Critical Emergency)
- **CV:** subject in prone / fallen position.
- **Accelerometer:** initial impact + continuous rhythmic low-amplitude oscillations (convulsions).
- **Heart rate:** instantaneous extreme spike (>130–160 BPM).
- **Action:** **bypass voice verification.** Fire webhooks (note suspected seizure) + open WebRTC.

### Scenario C — Syncope / Cardiovascular Event (Tier 2: Critical Emergency)
- **CV / Accelerometer:** posture collapse or impact detected.
- **Heart rate:** severe bradycardia (<50 BPM) or complete loss of pulse.
- **Action:** **bypass voice verification.** Fire webhooks with critical-vitals alert + open WebRTC.

### Scenario D — False Positive (Tier 0: Dismissal)
- **CV:** bounding box lowers and quickly recovers, or tracking briefly drops.
- **Accelerometer:** no impact peak.
- **Heart rate:** stable baseline.
- **Action:** override the CV anomaly; resume standard monitoring with no prompts or alerts.

---

## Pipeline 2 Module Map

Each block in the runtime corresponds to one module in `kineticpulse/`. Use this as a quick navigation aid.

```
Capture           kineticpulse/vision/capture.py
  USB / CSI / RTSP / file source, bounded frame queue (drop-oldest)
        │
        ▼
Vision            kineticpulse/vision/detector.py    FallDetector (.pt / .onnx / .engine)
                  kineticpulse/vision/pose.py        Pretrained YOLOv8n-pose
                  kineticpulse/vision/features.py    Torso angle, AR, velocity, stillness
                  kineticpulse/temporal/stgcn.py     TemporalHead (TSSTG action classifier + heuristic fallback)
                  kineticpulse/temporal/tsstg.py     TSSTG checkpoint loader + 7->4 class collapse
                  kineticpulse/temporal/stgcn_model.py Two-stream ST-GCN architecture
        │
        ▼
Sensors           kineticpulse/sensors/tcp.py        TcpSensorServer (production path)
                  kineticpulse/sensors/ble.py        BleClient (legacy / fallback)
                  kineticpulse/sensors/mock.py       MockSensorClient (transport-agnostic)
                  kineticpulse/sensors/parser.py     SensorEvent + binary BLE decoders
                  kineticpulse/sensors/ppg.py        MAX30102 raw-PPG -> BPM
        │
        ▼
Fusion            kineticpulse/fusion/rules.py       Pose / accel / HR signature primitives
                  kineticpulse/fusion/tiers.py       PRD section 5 -> EmergencyTier
                  kineticpulse/fusion/engine.py      Async time-windowed evaluation loop
        │
        ▼
Voice             kineticpulse/voice/prompts.py      pyttsx3 voice prompt player
                  kineticpulse/voice/stt.py          faster-whisper + MockStt
                  kineticpulse/voice/safe_words.py   safe / distress keyword classifier
        │
        ▼
Alerts            kineticpulse/alerts/payload.py     AlertPayload builder (vitals + scenario)
                  kineticpulse/alerts/webhooks.py    Async httpx dispatcher
                  kineticpulse/webrtc/peer.py        aiortc peer + signaling client (fail-safe)
```

Entry point: `kineticpulse/main.py` (run with `python -m kineticpulse.main --config config.yaml`).

---

## Hardware Status

The wristband is being integrated incrementally. The runtime uses two
``WristbandConfig`` capability flags to track what is currently
available, so the system is end-to-end functional at every stage:

| Component | Status | Config flag |
|---|---|---|
| **MAX30102 heart-rate sensor** | In integration | `wristband.has_ppg_raw: true` |
| **ESP32 transmitter** | In integration — pivoted to **TCP/Wi-Fi** after BLE proved unstable in bench tests | `wristband.transport: tcp` |
| **Accelerometer (IMU)** | Not yet ordered | `wristband.has_accelerometer: false` |

### Wristband telemetry: TCP/Wi-Fi (current) and BLE (fallback)

The wearable team moved off BLE because peripheral disconnections were too
frequent. The runtime now defaults to a TCP transport: the **Jetson runs a
single-tenant TCP server** on `wristband.tcp_host:wristband.tcp_port`
(default `0.0.0.0:5555`), and the ESP32 connects in as a client and
pushes **newline-delimited JSON**. One event per line, UTF-8.

```
{"type":"hello","device":"esp32-kp-001","fw":"0.1.0","caps":["hr","accel","ppg"]}
{"type":"hr","bpm":72,"ts":1758291234567}
{"type":"accel","ax":0.10,"ay":0.02,"az":0.99,"ts":1758291234580}
{"type":"ppg","ir":[1234,1235,...],"red":[1100,1101,...],"ts":1758291234590}
{"type":"pulse_lost","duration_s":3.0,"ts":1758291235000}
```

The ESP32-side `ts` field is informational only — the Jetson timestamps
every event with its own clock when it parses the line, so fusion-engine
timing is identical regardless of transport. Reconnection is the
firmware's responsibility (the server simply keeps listening).

The legacy BLE client still ships in [kineticpulse/sensors/ble.py](kineticpulse/sensors/ble.py)
and can be re-activated by setting `wristband.transport: ble` (plus
`wristband.mac`); future BLE-capable wearables can adopt the existing path
without code changes.

### What "raw PPG streaming" means

The ESP32 firmware reads the MAX30102 FIFO and forwards the raw IR + Red
samples to the Jetson without computing BPM on the microcontroller. The
Jetson decodes those samples in [kineticpulse/sensors/ppg.py](kineticpulse/sensors/ppg.py)
and derives BPM via centred moving-average detrending plus peak detection
with a refractory period. The output is identical in shape to the
existing `HrSample` events the fusion engine consumes, so nothing else
in the pipeline changes when the firmware lands.

Over **TCP** the wire format is the JSON line shown above
(`{"type":"ppg","ir":[...],"red":[...]}`). Over **BLE** (legacy) it
defaults to `<II` per sample (little-endian uint32 IR then uint32 Red,
8 bytes per sample); adjust the `struct` format string in
`parse_ppg_packet` if the firmware uses something else.

Set `wristband.has_ppg_raw: false` if the firmware sends pre-computed
HR (BPM) directly instead of raw PPG bursts. Useful for bring-up testing
with any off-the-shelf compliant HR monitor (Polar strap, etc.).

### Degraded operation without the IMU

Until the accelerometer arrives, the four PRD §5 scenarios behave as
follows. This is enforced and tested in `tests/test_fusion_rules.py`.

| Scenario | With IMU | Without IMU (today) |
|---|---|---|
| **A — Standard fall** | Tier 1 verify (CV + impact + HR) | Tier 1 verify (CV + HR only) |
| **B — Suspected seizure** | Tier 2 bypass voice | **Degrades to Tier 1** — tremor signature unavailable, so the system asks "Are you okay?" instead of skipping straight to emergency dispatch |
| **C — Syncope / cardiac** | Tier 2 bypass voice | Tier 2 bypass voice (HR-only) |
| **D — False positive** | Tier 0 dismiss | Tier 0 dismiss (slightly more permissive without the "no impact" cross-check) |

This is a deliberate, safe degradation: every real fall is still caught;
the trade-off is that some Scenario B events trigger a 10-second voice
verification window instead of immediate escalation. Flipping
`has_accelerometer: true` after the IMU arrives restores full PRD §5
behaviour without any other code change.

---

## Tech Stack

- **Edge runtime:** Nvidia Jetson Orin Nano (JetPack 6.x). Pipeline 2 is tuned for the Ampere GPU + ~67 TOPS INT8 envelope, and falls back gracefully to CUDA, MPS, or CPU during development.
- **Language:** Python 3.9+
- **Detection model:** YOLOv8s, trained on the unified 4-class dataset (`fallen`, `falling`, `stand`, `sitting`). See [dataset/README.md](dataset/README.md) for the merge schema and the sitting label-noise caveat.
- **Pose backbone:** YOLOv8s-pose by default (~13 MB, COCO val AP ~60). Auto-downloads on first run. Swap to `yolov8n-pose.pt` (~6 MB, AP ~50) on tight hardware budgets, or `yolov8m-pose.pt` (~25 MB, AP ~66) for higher keypoint accuracy at the cost of FPS.
- **Temporal head:** Two-Stream Spatial-Temporal Graph CNN (TSSTG, GajuuzZ lineage), wired into the fusion engine. Loads `models/tsstg/tsstg-model.pth` byte-compatibly with the released checkpoint and collapses its 7-class output (Standing / Walking / Sitting / Lying Down / Stand up / Sit down / Fall Down) onto KineticPulse's 4-class schema. **EMA smoothing + hysteresis** stabilise the published label across posture transitions, and the smoothed `ActionLogits` is fed to `pose_signature()` so it can override the per-frame detector when the temporal head is confident (≥ `temporal.action_confidence_threshold`, default 0.55) or has produced a `stable_label`. Skeleton input is robust to camera angle and distance — exactly the failure mode the per-frame YOLO detector showed on laptop webcams. Falls back to a posture heuristic when weights are missing. The upstream Google Drive link is dead, so KineticPulse pulls the weights from a community mirror; setup steps are in [models/tsstg/README.md](models/tsstg/README.md).
- **Speech-to-Text:** `faster-whisper` (CTranslate2-backed Whisper-small.en).
- **Wristband link:** **TCP/Wi-Fi** (Jetson is the server, ESP32 is the client; newline-delimited JSON). BLE retained as a fallback transport behind `wristband.transport: ble`. A `--mock-ble` synthetic telemetry source bypasses both transports for development without hardware.
- **Heart-rate processing:** on-Jetson PPG decoder (`kineticpulse.sensors.ppg`) that consumes raw MAX30102 samples streamed from the ESP32 and derives BPM with a dependency-free peak detector. Same code path is used over TCP (parsed from the `{"type":"ppg",...}` payload) and BLE (parsed from the binary characteristic).
- **Wearable firmware:** ESP32 (C/C++ or MicroPython) — currently integrating MAX30102 PPG sensor; IMU pending order. See the [Hardware Status](#hardware-status) section.
- **Streaming:** WebRTC via `aiortc` (Jetson peer + authenticated WebSocket signaling + TURN-capable ICE config). Caregiver dashboard lives under `dashboard/`.
- **Alerting:** async `httpx` webhook dispatcher (SMS, Slack, 119 / 911 APIs).

---

## Getting Started

### Prerequisites

- Python 3.9+ (3.10 / 3.11 also tested).
- A CUDA-capable GPU is recommended for training but not required; the training script auto-falls back to CPU.
- For Jetson deployment: Nvidia Jetson Orin Nano with JetPack 6.x (provides TensorRT, NVENC, NVDEC).
- USB webcam + microphone + speaker on the deployment box (for dev, all three are optional thanks to the mock flags).

### 1. Clone + install

```bash
git clone https://github.com/kingsman1960/KineticPulse.git
cd KineticPulse
python -m venv .venv
# Windows:    .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Prepare the dataset

The three source datasets are not checked into git. Follow [dataset/README.md](dataset/README.md) to download them, then run the merge:

```bash
python scripts/merge_datasets.py
```

This produces `dataset/_merged/` with the unified 4-class layout (train ~2k images, val 266, test 100). Only the train split contains `sitting` examples — see [dataset/README.md](dataset/README.md) for the rationale.

### 3. Train the fall-posture detector

```bash
python scripts/train.py
# overrides:
python scripts/train.py --model yolov8n.pt --epochs 50 --batch 8
```

Best weights end up at `runs/detect/kp_v2_4cls/weights/best.pt` (the run name is configurable via `configs/train.yaml::name`).

**Reference checkpoint metrics** (Ultralytics 8.4.53, YOLOv8s, 35 epochs with early stopping at epoch 15; `runs/detect/kp_v2_4cls/weights/best.pt`):

| Split | Images | Instances | overall mAP50 | overall mAP50-95 | per-class mAP50 (`fallen` / `falling` / `stand`) | Notes |
|---|---:|---:|---:|---:|---|---|
| `val`  | 266 | 296 | **0.885** | 0.556 | 0.900 / 0.835 / 0.921 | balanced (`falling`=100, `stand`=148, `fallen`=48). **Honest baseline.** |
| `test` | 100 | 101 | 0.977 | 0.610 | 0.995 / 0.995 / 0.942 | skewed (`falling`=7, `stand`=93, `fallen`=1) — inflated by class imbalance |

`val` is the number to quote externally; `test` is inflated because the held-out test split happens to be ~92% `stand` instances and only 7 `falling` instances. Expect a real-world mAP50 of roughly **0.85 – 0.90** once the deployment domain is included. (Re-measure any time with `python scripts/eval.py --weights runs/detect/kp_v2_4cls/weights/best.pt --split val`.)

Neither split contains `sitting` instances (the Primary dataset has no `sitting` labels). The class is trained but only verifiable via the live-camera spot check below — and **the TSSTG temporal head fully covers `sitting` regardless** (live test: `stand` conf 0.85–0.93, `sitting` 0.55–0.82, `fallen` 0.49 on a top-down laptop webcam where the per-frame YOLO detector struggles).

### 4. Evaluate on the held-out test split

```bash
python scripts/eval.py --weights runs/detect/kp_v2_4cls/weights/best.pt
```

Prints per-class P / R / mAP50 / mAP50-95 and writes `runs/detect/eval_test/{report.json, confusion_matrix.png}`.

### 5. Export for deployment

```bash
# ONNX always works (laptop / Jetson):
python scripts/export.py --weights runs/detect/kp_v2_4cls/weights/best.pt --format onnx

# TensorRT engine - run this ON the Jetson:
python scripts/export.py --weights runs/detect/kp_v2_4cls/weights/best.pt --format engine --half
```

### 6. (Optional) Fetch the TSSTG action-classifier weights

Pipeline 2 includes a Two-Stream ST-GCN temporal head (TSSTG) that
classifies actions from a sequence of skeleton keypoints — far more
robust to camera angle / distance than the per-frame YOLO detector.
Without weights the runtime falls back to a posture heuristic; with
weights you get the full action classifier.

The upstream Google Drive link published by GajuuzZ is dead, so we
download from a community mirror:

```powershell
pip install gdown
python -m gdown --folder `
    "https://drive.google.com/drive/folders/1lrTI56k9QiIfMJhG9kzNjBzJh98KCIIO" `
    -O models/tsstg/_mirror
Move-Item models/tsstg/_mirror/TSSTG/tsstg-model.pth models/tsstg/tsstg-model.pth -Force
Remove-Item -Recurse -Force models/tsstg/_mirror   # optional cleanup
```

Expected size: 24,708,522 bytes. See [models/tsstg/README.md](models/tsstg/README.md)
for the full procedure (manual download fallback, verification command,
checkpoint contents).

### 7. Live spot-check the camera + classifier

`scripts/live_predict.py` ships three modes (Windows: `--backend DSHOW`
recommended for stability):

```bash
# A) Per-frame YOLOv8 detector overlay - quick sanity check:
python scripts/live_predict.py --camera 0 --backend DSHOW --apply-priority --show-rule

# B) Pose + TSSTG action classifier (requires the weights from step 6).
#    Draws the COCO-17 skeleton overlay, per-class confidence bars in
#    the lower-left, and the hysteresis-confirmed STABLE label top-right:
python scripts/live_predict.py --camera 0 --backend DSHOW --use-action-classifier

# C) Same as B, but in DATA-COLLECTION mode for TSSTG fine-tuning.
#    Press 1=fallen / 2=falling / 3=stand / 4=sitting to dump the most
#    recent 30 frames of keypoints to dataset/temporal_clips/<label>/:
python scripts/live_predict.py --camera 0 --backend DSHOW --record
```

Press `q` in the preview window to exit. Use `--no-skeleton` /
`--no-bars` if the overlay slows your CPU down.

### 8. (Optional) Fine-tune TSSTG on your own clips

Three tools turn deployment-domain footage into a fine-tuned TSSTG
checkpoint. The workflow is:

```bash
# (a) Sit in front of the camera and label live (fastest):
python scripts/live_predict.py --camera 0 --backend DSHOW --record

# (b) Or batch-extract from pre-recorded videos (use either folder
#     convention <root>/<label>/*.mp4, or --label LABEL):
python scripts/extract_keypoints.py --input data/raw_clips --out dataset/temporal_clips
python scripts/extract_keypoints.py --input data/sit_demo.mp4 --label sitting

# (c) Fine-tune the released TSSTG checkpoint on the collected .npz
#     clips. With --freeze-backbone only the final fcn linear layer is
#     trained, which is usually enough for a 200-clip dataset:
python scripts/train_temporal.py --epochs 40 --batch-size 16 --freeze-backbone

# (d) Plug the fine-tuned weights back in by overriding --tsstg-weights:
python scripts/live_predict.py --use-action-classifier \
    --tsstg-weights models/tsstg/finetune-<run>/best.pth
```

Both record mode and the extract script share the same on-disk schema
(`dataset/temporal_clips/<label>/*.npz` with `keypoints (T, 17, 3)`,
`label`, `fps`, `image_size`, `video_path`), so they compose freely.

### 9. Run the Pipeline 2 runtime

```bash
cp config.example.yaml config.yaml      # then edit: webhook URLs, wristband MAC, etc.

# Dev laptop - no wristband, no microphone:
python -m kineticpulse.main --config config.yaml --mock-ble --mock-stt

# Scripted fall scenario from the mock sensor client (great for end-to-end smoke testing):
python -m kineticpulse.main --config config.yaml --mock-ble --mock-ble-scenario fall_b_seizure --mock-stt

# Timed run for CI / smoke tests (stops itself after N seconds):
python -m kineticpulse.main --config config.yaml --mock-ble --mock-stt --no-camera --max-runtime-s 3

# Jetson with real wristband + mic:
python -m kineticpulse.main --config config.yaml
```

### 10. Run the unit tests

```bash
python -m pytest tests/ -v
```

**84 tests** cover:

- **Pose-feature math** (14) — torso angle, AR, velocity, stillness primitives.
- **Fusion / PRD §5 scenarios** (7) — one happy path per scenario A/B/C/D plus HR-only degradation paths (no-IMU regime).
- **Fusion ↔ ActionLogits wiring** (8) — temporal head overrides, stable-label vs. confidence-threshold paths, scenario-A promotion, queue ingestion, backwards compatibility when `actions=None`.
- **Temporal stabilisation** (6) — EMA smoothing of raw probabilities, hysteresis latching, oscillation pinning, immediate-latch mode, helper accessors.
- **MAX30102 PPG decoder** (10) — raw-FIFO unpack + on-Jetson BPM estimator at 55 / 72 / 95 / 130 BPM.
- **TCP sensor server** (4) — HR / accel / `pulse_lost` decoding, malformed-input recovery, reconnection, raw-PPG passthrough.
- **Detector smoke** (1) — runs `FallDetector` on a real image, skipped when no weights.
- **Pipeline smoke** (3) — end-to-end orchestrator runs (two via the mock sensor source, one via a **real TCP loopback** that drives the full async pipeline).
- **Posture post-processor** — `sitting` / `falling` / `fallen` rescue from `stand` suppression, IoU grouping (priority rules used by `live_predict.py`).
- **Temporal subsystem** — graph builder, COCO-17 → coco_cut adapter, two-stream forward pass, `ActionLogits` schema, `TemporalHead` heuristic fallback when weights are absent.
- **Webhook dispatcher** (6) — disabled-webhook short-circuit, header / payload contract, parallel fan-out, single-failure isolation, lazy client lifecycle.

---

## Project Structure

```
KineticPulse/
├── kineticpulse/                # Pipeline 2 runtime package
│   ├── main.py                  # async orchestrator + CLI
│   ├── config.py                # YAML -> dataclass loader
│   ├── vision/
│   │   ├── capture.py           # USB / CSI / RTSP / file source + bounded frame queue
│   │   ├── detector.py          # FallDetector (.pt / .onnx / .engine backends)
│   │   ├── pose.py              # pretrained YOLOv8-pose wrapper (default: yolov8s-pose)
│   │   ├── features.py          # torso angle, AR, velocity, stillness
│   │   └── posture_postprocess.py  # priority rules: rescue sitting/fallen/falling from stand suppression
│   ├── temporal/
│   │   ├── types.py             # ActionLogits dataclass (zero non-stdlib deps; shared with fusion/rules.py)
│   │   ├── stgcn.py             # TemporalHead - TSSTG or heuristic + EMA + hysteresis; KeypointRingBuffer
│   │   ├── stgcn_model.py       # Two-stream ST-GCN architecture (matches tsstg-model.pth state_dict)
│   │   ├── tsstg.py             # TsstgClassifier - loads checkpoint, runs inference, collapses 7->4 classes
│   │   ├── keypoint_adapter.py  # COCO-17 (YOLOv8-pose) -> coco_cut 14 (with synthetic neck)
│   │   └── graph.py             # coco_cut skeleton graph + spatial / distance / uniform partitioning
│   ├── sensors/
│   │   ├── tcp.py               # TcpSensorServer - JSON-lines wristband stream (production)
│   │   ├── ble.py               # bleak BLE client (legacy / fallback transport)
│   │   ├── mock.py              # MockSensorClient - scripted PRD scenarios, no hardware
│   │   ├── parser.py            # SensorEvent + binary BLE decoders
│   │   └── ppg.py               # MAX30102 raw PPG decoder + on-Jetson HR processor
│   ├── voice/
│   │   ├── stt.py               # faster-whisper STT + MockStt
│   │   ├── prompts.py           # pyttsx3 voice prompt player
│   │   └── safe_words.py        # safe / distress keyword classification
│   ├── fusion/
│   │   ├── rules.py             # signature primitives (pose / accel / HR)
│   │   ├── tiers.py             # PRD section 5 scenarios A-D -> emergency tiers
│   │   └── engine.py            # async time-windowed fusion loop
│   ├── alerts/
│   │   ├── payload.py           # alert payload builder (subject, location, vitals)
│   │   └── webhooks.py          # async httpx webhook dispatcher
│   ├── webrtc/
│   │   ├── peer.py              # aiortc peer lifecycle (offer/answer/ICE + safe fallback)
│   │   ├── signaling_client.py  # WebSocket signaling client for Jetson peer
│   │   ├── tracks.py            # OpenCV camera -> aiortc video track
│   │   └── types.py             # ICE/session metadata dataclasses
│   └── utils/
│       ├── logging.py
│       └── timing.py
├── scripts/
│   ├── merge_datasets.py        # 3-dataset merge + dHash dedup (Option A schema)
│   ├── train.py                 # YOLOv8 training driver
│   ├── eval.py                  # per-class metrics + confusion matrix
│   ├── export.py                # ONNX (always) + TensorRT engine (Jetson)
│   ├── live_predict.py          # webcam spot-check: detector / pose+TSSTG / data-collection (--record)
│   ├── extract_keypoints.py     # video file(s) -> labelled keypoint clips (.npz) for TSSTG fine-tune
│   └── train_temporal.py        # TSSTG fine-tune on .npz clips, init from upstream weights
├── configs/
│   └── train.yaml               # training hyperparameters
├── tests/                       # 84 tests total
│   ├── test_features.py                # pose math (14)
│   ├── test_fusion_rules.py            # PRD section 5 scenarios + HR-only degradation (7)
│   ├── test_fusion_action_logits.py    # ActionLogits ↔ fusion-engine wiring (8)
│   ├── test_temporal_stabilisation.py  # EMA + hysteresis (6)
│   ├── test_ppg.py                     # MAX30102 raw decoder + BPM estimator (10)
│   ├── test_tcp_sensor.py              # TcpSensorServer decoders + reconnection (4)
│   ├── test_detector_smoke.py          # FallDetector on a real image (auto-skipped when no weights)
│   ├── test_pipeline_smoke.py          # end-to-end orchestrator + real TCP loopback (3)
│   ├── test_posture_postprocess.py     # sitting/falling/fallen rescue priority rules
│   ├── test_temporal_stgcn.py          # graph, COCO-17 adapter, two-stream forward, TemporalHead fallback
│   ├── test_webhooks.py                # async httpx dispatcher (6)
│   └── test_webrtc_config.py           # WebRTC config + ICE server parsing defaults (2)
├── models/
│   └── tsstg/
│       ├── README.md            # how to fetch tsstg-model.pth (community mirror)
│       └── tsstg-model.pth      # gitignored, 24.7 MB, see Getting Started step 6
├── dataset/
│   ├── README.md                # source datasets, unified schema, merge rationale
│   ├── _merged/                 # generated, gitignored
│   └── temporal_clips/          # gitignored, output of --record / extract_keypoints.py
│       ├── fallen/  *.npz
│       ├── falling/ *.npz
│       ├── stand/   *.npz
│       └── sitting/ *.npz
├── docs/
│   ├── MANUAL.md                # developer manual (repo map, module guide, cookbook, PR checklist)
│   └── WEBRTC_ROLLOUT.md        # production rollout gates (signaling/TURN/reliability)
├── dashboard/                   # Next.js caregiver UI + signaling server + coturn templates
├── config.example.yaml          # runtime config template
├── requirements.txt
└── README.md
```

---

## Non-Functional Requirements

- **Connectivity reliability** — TCP keepalive + idle-timeout on the Jetson side and ESP32-side reconnection on signal drops. (BLE auto-reconnect retained in `BleClient` for the fallback transport.)
- **Power efficiency (wearable)** — firmware tuned for **24–48 hours** of battery life.
- **Time synchronization** — wristband telemetry and webcam frames must be tightly time-aligned on the Jetson so the fusion engine evaluates the same instant across modalities.

---

## Roadmap

- [x] Dataset merge tooling (`scripts/merge_datasets.py`) with unified 4-class schema (`fallen` / `falling` / `stand` / `sitting`)
- [x] Jetson-side scaffold (`kineticpulse/` package, config loader, logging)
- [x] YOLOv8 training / eval / export pipeline (`scripts/train.py`, `scripts/eval.py`, `scripts/export.py`)
- [x] FallDetector with `.pt` / `.onnx` / `.engine` backends
- [x] Pose backbone wrapper (pretrained YOLOv8s-pose, configurable n / m / l variants) + pose feature extractor
- [x] TCP/Wi-Fi telemetry server (`TcpSensorServer`, JSON-lines wire format) + BLE fallback (`BleClient`, auto-reconnect) + transport-agnostic `MockSensorClient` scenarios
- [x] Local STT (faster-whisper) + voice-prompt routine + mock STT
- [x] Sensor-fusion engine (Tiers 0–2) implementing PRD section 5 scenarios A–D
- [x] Webhook dispatcher (async, parallel, timeout-bounded)
- [x] Unit tests: pose math + one per PRD scenario
- [ ] Train + report a first checkpoint on `dataset/_merged` (Phase 1 deliverable)
- [ ] CSI / RTSP camera bring-up on a real Jetson Orin Nano
- [x] Two-stream ST-GCN action classifier (TSSTG) integrated + weights in place (community-mirrored `tsstg-model.pth`); live spot-check via `scripts/live_predict.py --use-action-classifier` works
- [x] `ActionLogits` wired into the fusion engine — `pose_signature()` now consumes the temporal head, EMA + hysteresis published as `stable_label`, fusion snapshots carry `action_class` / `action_conf`, alert payload exposes them downstream (see MANUAL §8.4)
- [x] TSSTG fine-tuning toolchain — `scripts/live_predict.py --record` (live labelling), `scripts/extract_keypoints.py` (video → `.npz` clips), `scripts/train_temporal.py` (BCE fine-tune over the upstream 7-class head with optional `--freeze-backbone`); collection of deployment-domain clips and the actual fine-tune run are still TODO.
- [ ] Optional: detector → `falling` recall pass — current val recall on `falling` is 0.69; expanding the dataset with mid-fall transition frames is the lowest-hanging fruit on the per-frame side
- [x] WebRTC peer + caregiver dashboard baseline (aiortc Jetson peer, authenticated signaling server, Next.js session viewer, TURN-ready config + rollout checklist)
- [ ] ESP32 wristband firmware (IMU + PPG HR + **TCP client emitting JSON lines per the schema in [Hardware Status](#hardware-status)**)
- [ ] Battery-life optimization pass on the wristband

---

## Team & Task Assignment

### Team Structure

| Name | Role | Division |
|------|------|----------|
| **Youngwon Cho** | Software Development Lead | Software |
| Chang-Ting Zhong | Software Engineer | Software |
| Ren-Yi Huang | Software Engineer | Software |
| **Hao-Yuan Weng** | Hardware Development Lead (sensor chip integration) | Hardware |
| Yule Xu | Hardware Engineer | Hardware |
| Yuanhao Chen | Hardware Engineer | Hardware |
| **Yiyuan Chen** | Documentation & Reporting Lead | Documentation |
| Yong Zhe Sam | — | Cross-functional |

### Work Assignment Overview

Status legend: **Done** = merged to `main` and verified · **In Progress** = active branch or partial integration · **Pending** = not yet started

#### Software Division — Lead: Youngwon Cho

| Task | Assignee | Status |
|------|----------|--------|
| Pipeline 2 runtime scaffold (`kineticpulse/` package, config loader, async orchestrator) | Youngwon Cho | **Done** |
| Unified 4-class dataset merge + YOLOv8 train / eval / export pipeline | Youngwon Cho | **Done** |
| FallDetector + YOLOv8-pose backbone + pose feature extractor | Youngwon Cho | **Done** |
| Sensor-fusion engine (PRD §5 scenarios A–D, Tier 0–2) | Youngwon Cho | **Done** |
| TCP/Wi-Fi wristband telemetry server + BLE fallback + `MockSensorClient` | Youngwon Cho | **Done** |
| MAX30102 raw-PPG → BPM decoder (`kineticpulse/sensors/ppg.py`) | Youngwon Cho | **Done** |
| Voice verification stack (faster-whisper STT, prompts, safe-word classifier) | Youngwon Cho | **Done** |
| Webhook alert dispatcher (`kineticpulse/alerts/webhooks.py`) | Youngwon Cho | **Done** |
| `live_predict.py` webcam spot-check tool (detector / pose / record modes) | Youngwon Cho | **Done** |
| Two-stream ST-GCN (TSSTG) action classifier integration | Youngwon Cho | **Done** |
| `ActionLogits` → fusion-engine wiring + EMA / hysteresis stabilisation | Youngwon Cho | **Done** |
| TSSTG fine-tuning toolchain (`extract_keypoints.py`, `train_temporal.py`, `--record`) | Youngwon Cho | **Done** |
| WebRTC peer + authenticated signaling + caregiver dashboard (`dashboard/`) | Youngwon Cho | **Done** |
| Developer manual — primary author (`docs/MANUAL.md`) | Youngwon Cho | **Done** |
| Webhook dispatcher behaviour tests (`tests/test_webhooks.py`, PR #1) | Yuanhao Chen | **Done** |
| TCP wristband simulator + contract tests (`scripts/tcp_wristband_simulator.py`) | Chang-Ting Zhong | In Progress |
| ESP32 TCP telemetry wire-format documentation (`docs/TCP_CONTRACT.md`) | Chang-Ting Zhong | In Progress |
| CSI / RTSP camera bring-up on Jetson Orin Nano | Ren-Yi Huang | Pending |
| Phase 1 checkpoint training + metrics report on `dataset/_merged` | Ren-Yi Huang | Pending |
| Detector `falling` recall pass — mid-fall transition frame collection | Chang-Ting Zhong | Pending |
| WebRTC production rollout (TURN deployment, `docs/WEBRTC_ROLLOUT.md` gates) | Ren-Yi Huang | Pending |
| `config.example.yaml` field documentation audit | Yong Zhe Sam | In Progress |
| Safe-keyword / distress lexicon review (`kineticpulse/voice/safe_words.py`) | Yong Zhe Sam | Pending |
| TSSTG weights setup guide review (`models/tsstg/README.md`) | Yong Zhe Sam | Pending |

#### Hardware Division — Lead: Hao-Yuan Weng

| Task | Assignee | Status |
|------|----------|--------|
| ESP32-S3 PlatformIO development environment (`platformio.ini`, PR #2) | Hao-Yuan Weng | **Done** |
| I2C bus scanner firmware test (`src/i2c_scanner.cpp`, PR #2) | Hao-Yuan Weng | **Done** |
| ESP32 TCP client prototype — fake HR JSON telemetry (`src/main.cpp`, PR #2) | Hao-Yuan Weng | **Done** |
| MAX30102 PPG sensor chip integration on wristband PCB | Hao-Yuan Weng | In Progress |
| MAX30102 firmware driver — raw IR/Red FIFO streaming over TCP | Yule Xu | In Progress |
| IMU accelerometer procurement + board integration | Yule Xu | Pending |
| Production ESP32 wristband firmware (full JSON-lines schema) | Hao-Yuan Weng | Pending |
| Wristband battery-life optimisation (24–48 h target) | Yule Xu | Pending |
| BLE transport bench validation (fallback path) | Yuanhao Chen | Pending |
| Jetson-side TCP sensor decoder validation (`tests/test_tcp_sensor.py` review) | Yuanhao Chen | In Progress |

#### Documentation Division — Lead: Yiyuan Chen

| Task | Assignee | Status |
|------|----------|--------|
| README maintenance & getting-started guide | Yiyuan Chen | In Progress |
| `docs/MANUAL.md` — hardware-integration milestone sections (§8) | Yiyuan Chen | In Progress |
| `docs/WEBRTC_ROLLOUT.md` production rollout checklist | Yiyuan Chen | Pending |
| Internal PRD v3.0 alignment & progress report | Yiyuan Chen | Pending |
| Dataset merge rationale write-up (`dataset/README.md`) | Yiyuan Chen | In Progress |

> **PR merge record:** Software lead Youngwon Cho reviewed and merged PR #1 (webhook tests, Yuanhao Chen) and PR #2 (ESP32-S3 bring-up, Hao-Yuan Weng).

---

## Contributing

Contributions, issues, and feature requests are welcome. Please open an issue first to discuss any major change so we can align on scope and design.

1. Fork the repository
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Commit your changes
4. Push to the branch and open a Pull Request

---

## License

License to be determined. Until a license file is added, all rights are reserved by the project owner.

---

## Acknowledgements

Project requirements derived from the internal PRD *"Edge-AI Fall Detection & Intelligent Emergency Response System — v3.0 (Sensor Fusion Update)."*
