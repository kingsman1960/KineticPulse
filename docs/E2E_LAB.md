# Lab end-to-end checklist

Goal: one green path — **Jetson + wristband TCP + webcam + Tailscale + Galaxy APK + dashboard real mode**.

## 0. Prerequisites

- [ ] Jetson on network; SSH works (no monitor needed)
- [ ] Repo cloned; `./bootstrap.sh` already run once
- [ ] Tailscale on Jetson + caregiver phone/laptop (same tailnet)
- [ ] ESP32 flashed with contract-compatible firmware ([`src/main.cpp`](../src/main.cpp))
- [ ] Galaxy: KineticPulse **APK** (not Expo Go)

## 1. Jetson runtime

```bash
sudo systemctl status kineticpulse-signaling kineticpulse
# or foreground smoke:
./kineticpulse --mock-stt
```

- [ ] Log: `TCP: listening on ...:5555`
- [ ] Log: `Monitoring HTTP listening on ...:8790`
- [ ] `curl -s http://127.0.0.1:8790/monitoring | head` returns JSON

## 2. Wristband

```bash
cp src/wifi_secrets.h.example src/wifi_secrets.h   # set SSID + Jetson IP
pio run -e seeed_xiao_esp32s3 -t upload
```

- [ ] Serial: `WiFi OK` + `TCP connect ... ok`
- [ ] Jetson log: `TCP: wristband connected` + `hello`
- [ ] `curl` monitoring → `sensor.connection` = `"connected"`, `latest_hr_bpm` updates

If IMU not on board yet, leave `has_accelerometer: false` in `config.yaml`. Synthetic `accel` lines still parse; Scenario B full bypass needs a real IMU later.

## 3. Camera

- [ ] Webcam/CSI attached; not using `--no-camera`
- [ ] Log shows detector/pose activity (or expected weight load messages)

## 4. Dashboard (real vitals)

On laptop (same tailnet), from `deploy/handoff/caregiver.env`:

```bash
cp deploy/handoff/caregiver.env dashboard/.env.local
# ensure MONITORING_DATA_MODE=real and KINETICPULSE_MONITORING_HTTP_URL=http://<ts-ip>:8790/monitoring
cd dashboard && npm run dev
```

- [ ] http://localhost:3000 shows live HR / sensor connected
- [ ] Tier/vision fields update (not stuck on mock scenarios)

## 5. Mobile (Galaxy)

- [ ] Tailscale connected
- [ ] APK installed; **Scan setup QR** (`/handoff?token=...` or `caregiver-qr.png`)
- [ ] Session list loads from signaling `:8787`
- [ ] Trigger Tier 1/2 (mock scenario or real fall) → join → video < ~5s

Trigger without falling on camera:

```bash
./kineticpulse --mock-ble --mock-ble-scenario fall_b_seizure --mock-stt
```

(Use real TCP wristband instead of `--mock-ble` once step 2 is green.)

## 6. Pass criteria

| Check | Pass |
|-------|------|
| Wristband → Jetson TCP | hello + hr lines |
| Monitoring → dashboard | BPM changes live |
| Signaling → phone | sessions list |
| WebRTC | video on Galaxy |
| Tailscale | works off home Wi‑Fi |

Anything red above = still hypothesis, not a demo.
