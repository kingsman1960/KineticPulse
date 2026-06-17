# WebRTC Rollout Checklist

This checklist is the staged rollout gate for internet-ready caregiver streaming.

## 1) Signaling health

- [ ] Signaling server reachable over HTTPS/WSS only.
- [ ] `JETSON_SIGNAL_TOKEN` and `CAREGIVER_SIGNAL_TOKEN` set and rotated.
- [ ] `ALLOWED_ORIGINS` configured to explicit dashboard origins.
- [ ] `/sessions` endpoint requires auth and returns active sessions.

## 2) TURN readiness

- [ ] `coturn` deployed from `dashboard/deploy/docker-compose.turn.yml`.
- [ ] TLS certificate configured (`fullchain.pem`/`privkey.pem`).
- [ ] External IP, realm, and static secret configured.
- [ ] Jetson `config.yaml` has `webrtc.ice_servers` set to STUN + TURN URLs.

## 3) Functional tests

### LAN
- [ ] Trigger Tier1/Tier2 alert and verify session appears in dashboard.
- [ ] Caregiver joins and sees remote video in < 5 seconds.
- [ ] Ending session from either side closes both peers.

### Internet / NAT
- [ ] Repeat from different NATs (e.g., LTE hotspot vs office Wi-Fi).
- [ ] Verify stream still establishes (TURN relay path).
- [ ] Confirm only one caregiver viewer can join v1 session.

## 4) Failure handling

- [ ] Disable signaling server and confirm webhook dispatch still succeeds.
- [ ] Drop network mid-call and verify session cleanup by TTL.
- [ ] Verify runtime recovers for next alert without restart.

## 5) Observability

- [ ] Capture logs for signaling auth failures, offer/answer, and ICE exchange.
- [ ] Track session startup latency and failure rate over 24h soak run.
- [ ] Record top failure reasons for next iteration (NAT, token, TURN auth).
