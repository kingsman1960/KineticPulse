# Jetson Deployment Guide

Step-by-step instructions for installing and running **KineticPulse Pipeline 2** on an **Nvidia Jetson** (Jetson Linux / Ubuntu). Intended for team members deploying to edge hardware for academic development.

For system topology (signaling, WebRTC, wristband TCP), see [SERVER_ARCHITECTURE.md](SERVER_ARCHITECTURE.md).

---

## Table of contents

1. [What you are deploying](#1-what-you-are-deploying)
2. [Hardware & software requirements](#2-hardware--software-requirements)
3. [Quick start (clone → install → run)](#3-quick-start-clone--install--run)
4. [Configure `config.yaml`](#4-configure-configyaml)
5. [Smoke test without hardware](#5-smoke-test-without-hardware)
6. [Production run](#6-production-run)
7. [Start on boot (systemd)](#7-start-on-boot-systemd)
8. [Shipped model weights](#8-shipped-model-weights)
9. [Updating after `git pull`](#9-updating-after-git-pull)
10. [Troubleshooting](#10-troubleshooting)
11. [Related docs](#11-related-docs)

---

## 1. What you are deploying

On the Jetson, a single process orchestrates:

| Stage | What it does |
|-------|----------------|
| **Vision** | USB webcam → YOLO fall-posture detector + pose keypoints |
| **Temporal** | TSSTG action classifier over a sliding keypoint window |
| **Sensors** | TCP server on port **5555** for ESP32 wristband JSON telemetry |
| **Fusion** | Combines CV + vitals → emergency tier (A/B/C/D scenarios) |
| **Voice** | TTS prompt + local STT verification (Tier 1) |
| **Alerts** | Webhook dispatch + optional WebRTC live feed |

The repo ships shell scripts so you do **not** need to remember long `python -m` commands:

| Script | Purpose |
|--------|---------|
| **[`bootstrap.sh`](../bootstrap.sh)** | **One-shot deploy** — runtime + signaling + tokens + `config.yaml` + systemd |
| [`install.sh`](../install.sh) | Python runtime only (manual / advanced) |
| [`kineticpulse`](../kineticpulse) | Launcher created by install/bootstrap |

---

## 2. Hardware & software requirements

### Target device

- **Nvidia Jetson Orin Nano** (or compatible Jetson with JetPack 6.x)
- Jetson Linux (Ubuntu-based) with **JetPack 6.x** recommended
- Network: Wi-Fi or Ethernet (WebRTC, webhooks, wristband TCP)

### Peripherals (production)

| Device | Notes |
|--------|-------|
| USB webcam | Default `camera.device: "0"` in config |
| USB microphone | Used by voice verification |
| Speaker | Plays the “Are you okay?” prompt |
| ESP32 wristband | Connects **to** the Jetson on TCP port **5555** |

### Software on the Jetson

- `git`, `python3`, `python3-venv`, `python3-pip` (installed automatically by `install.sh`)
- **PyTorch for Jetson** — usually provided by JetPack. `install.sh` creates the venv with `--system-site-packages` so the system PyTorch wheel is visible. If `import torch` fails after install, see [Troubleshooting](#pytorch-not-found).

### Repository access

Clone the **private** team repository (replace the URL with your org’s fork):

```bash
git clone git@github.com:YOUR_ORG/KineticPulse.git
cd KineticPulse
```

---

## 3. Quick start (one command)

After clone, run **one script**. It installs everything, generates auth tokens, wires WebRTC in `config.yaml`, installs systemd units, and starts the services.

```bash
git clone git@github.com:YOUR_ORG/KineticPulse.git
cd KineticPulse
chmod +x bootstrap.sh
./bootstrap.sh
```

`bootstrap.sh` does all of the following automatically:

| Step | What happens |
|------|----------------|
| Edge runtime | Calls `deploy/jetson/install.sh` (venv, Python deps, model weights check) |
| Node.js | Installs Node 20+ if missing |
| **Tailscale** | Installed by default (free mesh VPN — caregivers off-LAN) |
| Signaling | `npm install` in `dashboard/`, generates tokens in `deploy/.env.deploy` |
| Config | Sets `webrtc.enabled: true` and matching `auth_token` in `config.yaml` |
| Caregiver handoff | Writes `caregiver.env`, **`caregiver-qr.png`** (mobile scan), `DEPLOY_SUMMARY.txt` |
| systemd | `kineticpulse-signaling` + `kineticpulse` enabled and started |
| Summary | Prints URLs/tokens → `deploy/handoff/DEPLOY_SUMMARY.txt` |

### Tailscale (different Wi‑Fi / no Railway)

`bootstrap.sh` **installs Tailscale on the Jetson by default**. Caregivers install the [Tailscale app](https://tailscale.com/download) on laptop/phone and join the **same tailnet** — no paid cloud backend.

**First-time join on the Jetson** (pick one):

```bash
# Interactive (browser login)
sudo tailscale up --hostname=kineticpulse-jetson

# Unattended (one-time key from Tailscale admin → Settings → Keys)
TAILSCALE_AUTH_KEY=tskey-auth-... ./bootstrap.sh
```

After Tailscale is connected, re-run `./bootstrap.sh` once to refresh `caregiver.env` with the `100.x` Tailscale IP.

Skip Tailscale for lab LAN-only installs:

```bash
./bootstrap.sh --no-tailscale
```

### Options

```bash
./bootstrap.sh --with-dashboard   # also build Next.js UI on :3000 (heavier on Jetson)
./bootstrap.sh --no-start         # install only, do not systemctl start yet
./bootstrap.sh --no-tailscale     # LAN-only; no Tailscale package
```

### After bootstrap

Services should already be running:

```bash
sudo systemctl status kineticpulse-signaling
sudo systemctl status kineticpulse
```

View the generated credentials and URLs:

```bash
cat deploy/handoff/DEPLOY_SUMMARY.txt
```

### Caregiver mobile app (QR setup)

After bootstrap, caregivers need the setup QR. **The Jetson does not need a monitor** — use any of these:

| Method | When to use |
|--------|-------------|
| **Browser on laptop** (recommended) | Tailscale on laptop → open `http://<caregiver-host>:8787/handoff?token=<caregiver-token>` (printed at end of `./bootstrap.sh` and in `DEPLOY_SUMMARY.txt`) → show QR on screen → phone app scans it |
| **SCP** | `scp user@jetson-ip:~/KineticPulse/deploy/handoff/caregiver-qr.png .` → open on laptop |
| **SSH terminal** | `./bootstrap.sh` over SSH prints an ASCII QR in the terminal (if `qrencode` is installed) |
| **Manual** | Paste values from `deploy/handoff/caregiver.env` in app Settings |

Caregivers:

1. Install **Tailscale** + join the team tailnet  
2. Install the **built** KineticPulse mobile app ([mobile/README.md](../mobile/README.md) — not Expo Go)  
3. **Scan setup QR** in the app (home or Settings)  

No manual URL/token entry required when using the QR. Re-run `./bootstrap.sh` after Tailscale join to refresh the QR with the `100.x` address.

---

## 3b. Manual install (advanced)

Use this only if you do **not** want signaling/systemd auto-setup.

### Step 1 — Clone

```bash
git clone git@github.com:YOUR_ORG/KineticPulse.git
cd KineticPulse
```

### Step 2 — Install (runtime only)

```bash
chmod +x install.sh deploy/jetson/run
./install.sh
```

`install.sh` will:

1. Install system packages (`python3-venv`, audio libs, FFmpeg dev headers for WebRTC)
2. Create `.venv/` (with `--system-site-packages` on Jetson)
3. Install Python deps from `requirements-jetson-runtime.txt`
4. Copy `config.example.yaml` → `config.yaml` if missing
5. Create the `./kineticpulse` launcher
6. Print whether shipped model weights are present

> **sudo** is required for `apt-get` during install.

### Step 3 — Edit config

```bash
nano config.yaml   # or your preferred editor
```

At minimum, review [section 4](#4-configure-configyaml) before a live run.

### Step 4 — Run

**Smoke test (no camera / wristband / mic):**

```bash
./kineticpulse --mock-ble --mock-stt --no-camera --max-runtime-s 5
```

**Production (real hardware):**

```bash
./kineticpulse
```

Stop with `Ctrl+C`.

---

## 4. Configure `config.yaml`

`install.sh` creates `config.yaml` from [`config.example.yaml`](../config.example.yaml). `config.yaml` is gitignored — each Jetson keeps its own local copy.

### Must-review settings

| Section | Key fields | Action |
|---------|------------|--------|
| `camera` | `source`, `device`, `width`, `height` | Set USB index or CSI/RTSP URL |
| `detector` | `weights`, `device` | Default `runs/detect/kp_v2_4cls/weights/best.pt` (shipped) |
| `temporal` | `weights` | Default `models/tsstg/tsstg-model.pth` (shipped) |
| `wristband` | `tcp_port`, `has_accelerometer`, `has_ppg_raw` | Match ESP32 firmware capabilities |
| `alerts` | `subject_id`, `location`, `webhooks` | Set caregiver endpoints |
| `webrtc` | `enabled`, `signaling_url`, `auth_token`, `ice_servers` | See [WEBRTC_ROLLOUT.md](WEBRTC_ROLLOUT.md) |

### Wristband TCP (default production path)

The Jetson **listens**; the ESP32 **connects**:

```yaml
wristband:
  transport: tcp
  tcp_host: "0.0.0.0"
  tcp_port: 5555
```

Point firmware at `<jetson-lan-ip>:5555`.

### Inference device

Leave `device: auto` on Jetson unless you need to force CPU for debugging:

```yaml
detector:
  device: auto    # uses CUDA when available
pose:
  device: auto
temporal:
  device: auto
```

### Optional environment variables

| Variable | Effect |
|----------|--------|
| `KINETICPULSE_CONFIG` | Override config file path (default: `./config.yaml`) |
| `KINETICPULSE_EXTRA_ARGS` | Extra CLI flags for systemd, e.g. `--mock-ble` |

---

## 5. Smoke test without hardware

Use this after install or after `git pull` to confirm the pipeline starts cleanly:

```bash
./kineticpulse --mock-ble --mock-stt --no-camera --max-runtime-s 5
```

Expected log lines:

- `KineticPulse starting`
- `MockSensorClient: scenario=resting`
- `--no-camera set; skipping capture loop`
- Fusion engine monitoring / tier messages
- `--max-runtime-s reached; stopping`

### Scripted fall scenario

```bash
./kineticpulse --mock-ble --mock-ble-scenario fall_b_seizure --mock-stt --no-camera --max-runtime-s 8
```

You should see a **Tier 2** emergency path (voice bypass) in the logs.

---

## 6. Production run

### Before you start

- [ ] Webcam, mic, and speaker connected
- [ ] ESP32 wristband powered and configured with the Jetson’s IP + port `5555`
- [ ] `config.yaml` edited (webhooks, subject ID, WebRTC tokens if enabled)
- [ ] Signaling server running if `webrtc.enabled: true` (see [dashboard/README.md](../dashboard/README.md))

### Start the runtime

```bash
cd /path/to/KineticPulse
./kineticpulse
```

Equivalent manual invocation (same as the launcher):

```bash
source .venv/bin/activate
python -m kineticpulse.main --config config.yaml
```

### First run notes

- **Pose weights** (`yolov8s-pose.pt`) are **not** in git. Ultralytics downloads them on first use (~22 MB). Requires internet on first launch.
- **TensorRT** (optional): convert the detector on-device with `python scripts/export.py` for lower latency. Default `.pt` weights work out of the box.

---

## 7. Start on boot (systemd)

A template unit file ships at [`deploy/jetson/kineticpulse.service`](../deploy/jetson/kineticpulse.service).

1. Edit `User`, `Group`, and `WorkingDirectory` to match your Jetson user and clone path.

2. Install and enable:

```bash
sudo cp deploy/jetson/kineticpulse.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable kineticpulse
sudo systemctl start kineticpulse
```

3. Check status:

```bash
sudo systemctl status kineticpulse
journalctl -u kineticpulse -f
```

To pass extra flags via systemd, uncomment `Environment=KINETICPULSE_EXTRA_ARGS=...` in the unit file.

---

## 8. Shipped model weights

These checkpoints are **committed to the private repo** so `git clone` is sufficient on a fresh Jetson:

| Model | Path | Size (approx.) |
|-------|------|----------------|
| YOLOv8 fall-posture detector (4-class) | `runs/detect/kp_v2_4cls/weights/best.pt` | ~22 MB |
| TSSTG temporal action classifier | `models/tsstg/tsstg-model.pth` | ~24 MB |

`install.sh` prints `OK` / `MISSING` for each file.

**Not shipped** (by design):

| Model | How to obtain |
|-------|----------------|
| `yolov8s-pose.pt` | Auto-downloaded by Ultralytics on first pose inference |
| TensorRT `.engine` | Build on Jetson via `scripts/export.py` (optional) |

Verify weights load manually:

```bash
source .venv/bin/activate
python -c "
from pathlib import Path
from kineticpulse.config import DetectorConfig
from kineticpulse.vision.detector import FallDetector
d = FallDetector(DetectorConfig(weights='runs/detect/kp_v2_4cls/weights/best.pt', device='cpu'))
d.load()
print('detector OK')
"
```

---

## 9. Updating after `git pull`

```bash
cd /path/to/KineticPulse
git pull
./install.sh          # refreshes venv deps if requirements changed
./kineticpulse --mock-ble --mock-stt --no-camera --max-runtime-s 5
```

If only `config.example.yaml` changed, merge new keys into your local `config.yaml` manually (`config.yaml` is not tracked by git).

---

## 10. Troubleshooting

### `KineticPulse venv missing. Run once: ./install.sh`

Run `./install.sh` from the repo root.

### PyTorch not found

After `install.sh`, if you see a PyTorch warning:

1. Install the Jetson wheel matching your JetPack version:  
   [NVIDIA PyTorch for Jetson](https://docs.nvidia.com/deep-learning/frameworks/install-pytorch-jetson-platform/index.html)
2. Re-run `./install.sh`
3. Confirm: `source .venv/bin/activate && python -c "import torch; print(torch.__version__)"`

### Shipped weight reported `MISSING`

```bash
git lfs pull          # only if the repo later adopts LFS
git pull              # ensure you have the latest commit with weights
ls -lh runs/detect/kp_v2_4cls/weights/best.pt
ls -lh models/tsstg/tsstg-model.pth
```

### Camera not found

- List devices: `ls /dev/video*`
- Try `camera.device: "0"` or `"1"` in `config.yaml`
- Ensure no other process holds the webcam

### Wristband not connecting

- Confirm Jetson IP: `hostname -I`
- Confirm port open: `ss -tlnp | grep 5555` while `./kineticpulse` is running
- ESP32 must initiate the TCP connection **to** the Jetson

### Pose model download fails

- Check internet on first run
- Or pre-download on a dev machine and copy `yolov8s-pose.pt` into the repo root on the Jetson

### WebRTC / caregiver dashboard

See [SERVER_ARCHITECTURE.md](SERVER_ARCHITECTURE.md) and [WEBRTC_ROLLOUT.md](WEBRTC_ROLLOUT.md). Signaling runs separately under `dashboard/`.

---

## 11. Related docs

| Doc | Contents |
|-----|----------|
| [MANUAL.md](MANUAL.md) | Developer guide, module map, debugging |
| [SERVER_ARCHITECTURE.md](SERVER_ARCHITECTURE.md) | Signaling, WebRTC, TCP wristband topology |
| [WEBRTC_ROLLOUT.md](WEBRTC_ROLLOUT.md) | Production WebRTC / TURN checklist |
| [dashboard/README.md](../dashboard/README.md) | Caregiver dashboard + signaling server |
| [config.example.yaml](../config.example.yaml) | Full runtime config reference |

---

## Cheat sheet

```bash
# One-shot deploy (recommended)
git clone git@github.com:YOUR_ORG/KineticPulse.git
cd KineticPulse
chmod +x bootstrap.sh
./bootstrap.sh
cat deploy/handoff/DEPLOY_SUMMARY.txt
# Show QR to caregivers: deploy/handoff/caregiver-qr.png

# Caregiver phone: Tailscale + KineticPulse app → Scan setup QR

# Optional: dashboard on the Jetson too
./bootstrap.sh --with-dashboard

# Service logs
sudo journalctl -u kineticpulse-signaling -f
sudo journalctl -u kineticpulse -f
```
