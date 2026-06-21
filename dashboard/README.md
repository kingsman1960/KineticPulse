# Caregiver Dashboard + Signaling

This folder contains:

- a Next.js caregiver UI (`app/`)
- a WebSocket signaling server (`server/signaling-server.js`)
- a cross-platform mobile caregiver app (`../mobile/`) — Expo + React Native WebRTC for iOS/Android

## 1) Install

```bash
cd dashboard
npm install
```

## 2) Run signaling server

```bash
set JETSON_SIGNAL_TOKEN=replace_jetson_token
set CAREGIVER_SIGNAL_TOKEN=replace_caregiver_token
set ALLOWED_ORIGINS=http://localhost:3000,https://caregiver.example
npm run signal
```

Server defaults:

- HTTP: `http://localhost:8787/sessions` (session list)
- WS: `ws://localhost:8787/ws` (offer/answer/ICE relay)

## 3) Run dashboard

```bash
set NEXT_PUBLIC_SIGNALING_HTTP_BASE=http://localhost:8787
set NEXT_PUBLIC_SIGNALING_WS_BASE=ws://localhost:8787/ws
set NEXT_PUBLIC_CAREGIVER_TOKEN=replace_caregiver_token
npm run dev
```

Open http://localhost:3000

## Production notes

- Put signaling behind TLS and expose only `wss://...`.
- Configure TURN (`coturn`) and set `webrtc.ice_servers` in KineticPulse `config.yaml`.
- Keep `JETSON_SIGNAL_TOKEN` and `CAREGIVER_SIGNAL_TOKEN` long/random and rotate periodically.
- One viewer is allowed per session in v1 (`viewer_already_attached` for extra joins).
- Deploy templates:
  - `deploy/docker-compose.turn.yml`
  - `deploy/coturn.conf.example`
