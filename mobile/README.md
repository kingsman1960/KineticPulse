# KineticPulse Mobile (Caregiver)

Cross-platform caregiver dashboard for **iOS** and **Android**. Built with **Expo** + **react-native-webrtc**, using the same signaling protocol as the web dashboard (`dashboard/`).

UI follows the corporate design tokens in [`DESIGN.md`](../DESIGN.md) — light canvas, BMW blue primary CTAs, rectangular (0px) components, Inter 700/300 typography.

## Features

- Poll active emergency sessions from the signaling server
- Join a session and view the Jetson live WebRTC video feed
- Display alert context (tier, scenario, subject, location, detector/action labels)
- Configure signaling HTTP/WS endpoints, caregiver token, and ICE servers

## Prerequisites

- Node.js 18+
- For **iOS**: macOS with Xcode 15+ (simulator or device)
- For **Android**: Android Studio + SDK 34+
- Running KineticPulse signaling server (`dashboard/server/signaling-server.js`)

> **Note:** WebRTC requires a **development build**. Expo Go does not include `react-native-webrtc`. Use `npx expo run:ios` / `npx expo run:android` or EAS Build.

## 1) Start signaling (from repo root)

```bash
cd dashboard
npm install
set JETSON_SIGNAL_TOKEN=replace_jetson_token
set CAREGIVER_SIGNAL_TOKEN=replace_caregiver_token
npm run signal
```

## 2) Install mobile dependencies

```bash
cd mobile
npm install
```

## 3) Run on a device or emulator

### Android

```bash
npx expo prebuild --platform android
npx expo run:android
```

### iOS (macOS only)

```bash
npx expo prebuild --platform ios
npx expo run:ios
```

### Development server

In another terminal:

```bash
npm start
```

## 4) Configure the app

1. Open the app → **Server settings**
2. Set **HTTP base** to your signaling host, e.g. `http://192.168.1.10:8787`
3. Set **WebSocket base**, e.g. `ws://192.168.1.10:8787/ws`
4. Paste the **caregiver token** (`CAREGIVER_SIGNAL_TOKEN`)
5. Add TURN URLs when testing across NATs (one per line)

Use your PC's LAN IP — `localhost` only works on the same machine.

## Production builds (EAS)

```bash
npm install -g eas-cli
eas login
eas build --profile preview --platform all
```

Update `app.json` bundle identifiers (`de.tum.kineticpulse.caregiver`) before store submission.

## Architecture

```
Jetson (aiortc) ──create-session──▶ Signaling server ◀──join-session── Mobile app
                                         │
                                         ├── offer ──▶ Mobile
                                         ◀── answer ─── Mobile
                                         └── ICE relay ◀──▶ both peers
```

Mobile reuses the caregiver role from `dashboard/app/session/[id]/page.tsx`.

## Signaling server: native apps

When `ALLOWED_ORIGINS` is set, authenticated requests **without** an `Origin` header (native WebSocket) are allowed so iOS/Android clients can connect with a valid caregiver token.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `HTTP 401` on session list | Set caregiver token in Settings |
| `HTTP 403` / WebSocket fails | Check `ALLOWED_ORIGINS` or use token auth from mobile |
| Black video, `connected` | Verify Jetson WebRTC + camera; add TURN for NAT |
| Cannot reach server | Use LAN IP; Android emulator may need `10.0.2.2` for host machine |

## Related docs

- [dashboard/README.md](../dashboard/README.md) — web dashboard + signaling
- [docs/WEBRTC_ROLLOUT.md](../docs/WEBRTC_ROLLOUT.md) — production rollout checklist
