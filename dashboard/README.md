# Caregiver Dashboard + Signaling

> **Architecture:** [docs/SERVER_ARCHITECTURE.md](../docs/SERVER_ARCHITECTURE.md)  
> **Jetson deploy:** [docs/JETSON_DEPLOY.md](../docs/JETSON_DEPLOY.md) — use [`../bootstrap.sh`](../bootstrap.sh) for one-shot edge + signaling setup.

This folder contains:

- Next.js caregiver web UI (`app/`)
- WebSocket signaling server (`server/signaling-server.js`)
- Mobile caregiver app (`../mobile/`) — Expo + WebRTC; **scan setup QR** for zero-typing config

## Quick path: Jetson already bootstrapped

If `./bootstrap.sh` ran on the Jetson, signaling tokens and `.env.local` are already generated:

```bash
# On a caregiver laptop (same Tailscale tailnet)
cp /path/from/jetson/deploy/handoff/caregiver.env dashboard/.env.local
cd dashboard
npm install
npm run dev
```

Open http://localhost:3000

Mobile caregivers: scan `deploy/handoff/caregiver-qr.png` in the KineticPulse app (see [mobile/README.md](../mobile/README.md)).

---

## Manual local development

### 1) Install

```bash
cd dashboard
npm install
```

### 2) Run signaling server

```bash
# Linux / macOS
export JETSON_SIGNAL_TOKEN=replace_jetson_token
export CAREGIVER_SIGNAL_TOKEN=replace_caregiver_token
export ALLOWED_ORIGINS=http://localhost:3000

# Windows PowerShell
$env:JETSON_SIGNAL_TOKEN="replace_jetson_token"
$env:CAREGIVER_SIGNAL_TOKEN="replace_caregiver_token"

npm run signal
```

Defaults:

- HTTP: `http://localhost:8787/sessions`
- WS: `ws://localhost:8787/ws`

### 3) Run dashboard

```bash
export NEXT_PUBLIC_SIGNALING_HTTP_BASE=http://localhost:8787
export NEXT_PUBLIC_SIGNALING_WS_BASE=ws://localhost:8787/ws
export NEXT_PUBLIC_CAREGIVER_TOKEN=replace_caregiver_token
npm run dev
```

---

## Production notes

- Expose signaling over **HTTPS/WSS** when crossing the public internet (or use **Tailscale** and keep HTTP/WS on the tailnet).
- Configure TURN (`deploy/docker-compose.turn.yml`, `deploy/coturn.conf.example`) and set `webrtc.ice_servers` in Jetson `config.yaml`.
- Rotate `JETSON_SIGNAL_TOKEN` / `CAREGIVER_SIGNAL_TOKEN` periodically.
- One viewer per session in v1 (`viewer_already_attached`).

## Handoff files (from `bootstrap.sh`)

| File | Purpose |
|------|---------|
| `deploy/handoff/caregiver.env` | Web dashboard env vars |
| `deploy/handoff/caregiver-config.json` | QR payload (JSON) |
| `deploy/handoff/caregiver-qr.png` | Scan in mobile app |
| `deploy/handoff/DEPLOY_SUMMARY.txt` | URLs + tokens for the team |
