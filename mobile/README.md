# KineticPulse Mobile (Caregiver)

Cross-platform caregiver app for **iOS** and **Android**. Built with **Expo** + **react-native-webrtc**, using the same signaling protocol as the web dashboard (`dashboard/`).

UI follows the corporate design tokens in [`DESIGN.md`](../DESIGN.md).

## Features

- Poll active emergency sessions from the signaling server
- Join a session and view the Jetson live WebRTC video feed
- Display alert context (tier, scenario, subject, location, detector/action labels)
- **Scan setup QR** — no manual typing (payload from Jetson `bootstrap.sh`)
- Manual server settings (HTTP/WS base, caregiver token, ICE servers)

## Prerequisites

- Node.js 18+
- **iOS:** macOS + Xcode 15+ (device or simulator)
- **Android:** Android Studio + SDK 34+
- Jetson deployed with [`../bootstrap.sh`](../bootstrap.sh) (signaling + Tailscale)
- Caregivers on **Tailscale** when not on the same Wi‑Fi as the Jetson

> **WebRTC requires a development build.** **Expo Go does not work** (`react-native-webrtc` is native). Use `eas build` or `npx expo run:android` / `run:ios`.

## Caregiver onboarding (production)

1. Install [Tailscale](https://tailscale.com/download) and join the **team tailnet**
2. Install the **KineticPulse APK/IPA** (EAS or team build — see below)
3. Open app → **Scan setup QR** (or **Server settings**)
4. Scan `deploy/handoff/caregiver-qr.png` from the Jetson (created by `./bootstrap.sh`)

No typing required when using the QR. The QR encodes signaling URL, WebSocket URL, and caregiver token.

### Manual fallback

Settings → paste values from `deploy/handoff/caregiver.env` on the Jetson:

- HTTP base: `http://<jetson-tailscale-ip>:8787`
- WebSocket: `ws://<jetson-tailscale-ip>:8787/ws`
- Caregiver token: from `deploy/handoff/DEPLOY_SUMMARY.txt`

## Build the app (team — one time per release)

### EAS cloud build (recommended for distribution)

```bash
cd mobile
npm install
npm install -g eas-cli
eas login
eas build --profile preview --platform android   # APK for internal install
eas build --profile preview --platform ios       # needs Apple Developer account
```

Share the EAS download link with caregivers.

### Local development build

```bash
cd mobile
npm install
npx expo prebuild --platform android
npx expo run:android
```

iOS (macOS only):

```bash
npx expo prebuild --platform ios
npx expo run:ios
```

Dev server (separate terminal): `npm start`

## Local dev against a laptop signaling server

If not using Jetson bootstrap yet:

```bash
cd dashboard
npm install
export JETSON_SIGNAL_TOKEN=dev-jetson
export CAREGIVER_SIGNAL_TOKEN=dev-caregiver
npm run signal
```

Then either scan a hand-crafted QR (JSON v1 — see `deploy/handoff/caregiver-config.json` format) or enter `http://<lan-ip>:8787` in Settings.

## QR payload format

Written by [`deploy/scripts/write_caregiver_handoff.py`](../deploy/scripts/write_caregiver_handoff.py):

```json
{"v":1,"signalingHttpBase":"http://100.x.x.x:8787","signalingWsBase":"ws://100.x.x.x:8787/ws","caregiverToken":"...","iceServersText":"stun:stun.l.google.com:19302"}
```

The app also accepts plain `caregiver.env` text inside a QR.

## Architecture

```
Jetson (aiortc) ──create-session──▶ Signaling :8787 ◀──join-session── Mobile app
                                         │
                                         ├── offer ──▶ Mobile
                                         ◀── answer ─── Mobile
                                         └── ICE relay ◀──▶ both peers
```

Mobile reuses the caregiver role from `dashboard/app/session/[id]/page.tsx`.

## Signaling: native apps

When `ALLOWED_ORIGINS` is set, authenticated requests **without** an `Origin` header (React Native WebSocket) are still allowed with a valid caregiver token.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `HTTP 401` | Wrong caregiver token — re-scan QR from Jetson |
| `Network request failed` | Tailscale off, or URL still `localhost` |
| Invalid QR | Re-run `./bootstrap.sh` on Jetson to regenerate `caregiver-qr.png` |
| Black video | Jetson `kineticpulse` running; same tailnet; check WebRTC logs |
| Expo Go | Use a **built** app — WebRTC not in Expo Go |

## Related docs

- [docs/JETSON_DEPLOY.md](../docs/JETSON_DEPLOY.md) — Jetson one-shot `bootstrap.sh`
- [dashboard/README.md](../dashboard/README.md) — web dashboard + signaling
- [docs/WEBRTC_ROLLOUT.md](../docs/WEBRTC_ROLLOUT.md) — production WebRTC checklist
