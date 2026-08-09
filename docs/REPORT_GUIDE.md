# Project report pack (for documentation / progress writers)

**Audience:** teammates drafting the course / CPS progress report (esp. Documentation lead).  
**Goal:** one place to find cite-ready facts, figures sources, contribution status, and gaps — without reverse-engineering the whole repo.

Internal requirements source: PRD *“Edge-AI Fall Detection & Intelligent Emergency Response System — v3.0 (Sensor Fusion Update)”* (see repo `CPS ideas - Google Docs.pdf`).

---

## 1. Suggested report outline → where to copy from

| Report section | Primary sources in repo |
|----------------|-------------------------|
| Abstract / problem | [README.md](../README.md) — Why KineticPulse, Key Features |
| System architecture | This file §2 + [SERVER_ARCHITECTURE.md](SERVER_ARCHITECTURE.md) (update date: 2026-06-17 — **partially stale**, see §6) |
| Edge pipeline (CV + fusion) | [MANUAL.md](MANUAL.md) module map; README Pipeline 2 Module Map |
| Wearable / TCP | [TCP_CONTRACT.md](TCP_CONTRACT.md), README Hardware Status |
| Caregiver apps | [dashboard/README.md](../dashboard/README.md), [mobile/README.md](../mobile/README.md) |
| Deploy / lab demo | [JETSON_DEPLOY.md](JETSON_DEPLOY.md), [E2E_LAB.md](E2E_LAB.md) |
| Evaluation (CV metrics) | README “Reference checkpoint metrics”; `python scripts/eval.py` |
| Roles & contributions | README **Team & Task Assignment** |
| Limitations / future work | This file §5 + README Roadmap unchecked items |
| WebRTC ops | [WEBRTC_ROLLOUT.md](WEBRTC_ROLLOUT.md) |

---

## 2. Cite-ready system summary (current)

KineticPulse is an **edge-AI fall detection** stack on **NVIDIA Jetson Orin Nano**:

1. **Vision** — YOLOv8 4-class detector (`fallen` / `falling` / `stand` / `sitting`) + YOLOv8-pose + TSSTG temporal head  
2. **Wearable** — ESP32 wristband → Jetson **TCP :5555** NDJSON (`hr` / `accel` / `ppg`)  
3. **Fusion** — PRD §5 scenarios A–D → Tier 0 dismiss / Tier 1 voice verify / Tier 2 immediate escalate  
4. **Alerts** — async webhooks + **WebRTC** live video to caregiver  
5. **Caregiver** — Next.js dashboard (vitals via `GET :8790/monitoring`) + Expo Android/iOS app (EAS APK, not Expo Go)  
6. **Remote access** — **Tailscale** mesh (default in `bootstrap.sh`); signaling on Jetson `:8787`

```text
ESP32 --TCP:5555--> Jetson (fusion + WebRTC sender + /monitoring:8790)
                         |                |
                         | WS signaling   | HTTP vitals
                         v                v
                    :8787 signaling    Dashboard / Mobile
                         |
                         +-- WebRTC media (P2P / TURN optional)
```

**One-shot deploy:** `./bootstrap.sh` → runtime + signaling + Tailscale + systemd + caregiver QR.

---

## 3. Numbers you can quote (as of repo contents)

### Detector (val — prefer this over test)

Source: README reference checkpoint (`runs/detect/kp_v2_4cls/weights/best.pt`).

| Metric | Value |
|--------|------:|
| Val mAP50 | **0.885** |
| Val mAP50-95 | 0.556 |
| Per-class mAP50 (`fallen` / `falling` / `stand`) | 0.900 / 0.835 / 0.921 |
| Test mAP50 | 0.977 (skewed — do **not** lead with this) |

Caveats for honesty section:

- Val/test have **no `sitting` instances** (trained but only live/TSSTG verifies sitting).  
- `falling` recall still a known weakness (~0.69 mentioned in Roadmap).  
- Re-run: `python scripts/eval.py --weights runs/detect/kp_v2_4cls/weights/best.pt --split val`

### Tests / engineering evidence

| Item | Value |
|------|------:|
| Pytest collection | **89** tests (pose, fusion, PPG, TCP, webhooks, monitoring, smoke, …) |
| Dashboard | Vitest + `npm run typecheck` / `build` |
| Mobile | `npx tsc --noEmit`; WebRTC needs **dev/EAS build** |

### Ports (ops table)

| Port | Service |
|-----:|---------|
| 5555 | Wristband TCP |
| 8787 | Signaling HTTP/WS |
| 8790 | Monitoring JSON (`/monitoring`) |
| 3000 | Optional Next.js dashboard |

---

## 4. Contribution snapshot (for “who did what”)

Authoritative table: [README.md § Team & Task Assignment](../README.md#team--task-assignment).

| Division | Lead | Report angle |
|----------|------|--------------|
| Software | Youngwon Cho | Pipeline 2, WebRTC, deploy/bootstrap, mobile QR, monitoring integration |
| Hardware | Hao-Yuan Weng | ESP32-S3, I2C, TCP client; MAX30102 / IMU still in progress |
| Documentation | Yiyuan Chen | PRD alignment + progress report (**still open**); use this pack |

**Merged PRs on record:** #1 webhook tests (Yuanhao Chen), #2 ESP32 bring-up (Hao-Yuan Weng).

When writing individual contribution paragraphs, copy **Done / In Progress / Pending** rows rather than inventing status.

---

## 5. Limitations & future work (honest slide)

Use these — they match the code/config, not marketing:

1. **IMU not on board** → Scenario B (seizure) degrades to Tier 1 voice verify (`has_accelerometer: false`).  
2. **ESP32 PPG** — contract-aligned firmware can send synthetic `hr`/`accel`; real MAX30102 `ppg` path still hardware-owned.  
3. **WebRTC TURN** — checklist in `WEBRTC_ROLLOUT.md` largely unchecked; lab relies on **Tailscale / LAN**.  
4. **TSSTG** — upstream weights integrated; **deployment-domain fine-tune** not completed.  
5. **CSI/RTSP on Jetson** — pending real-camera bring-up task.  
6. **License** — TBD in README.  
7. **E2E lab** — procedure in `E2E_LAB.md`; report should say whether checklist was green or not.

---

## 6. Doc freshness warnings (do not blindly paste)

| Doc | Issue |
|-----|--------|
| [SERVER_ARCHITECTURE.md](SERVER_ARCHITECTURE.md) | Dated **2026-06-17**. Missing: Tailscale-first deploy, `bootstrap.sh`, monitoring `:8790`, caregiver QR handoff, Jetson co-hosted signaling as default. Prefer §2 of **this** file for “current topology”. |
| [MANUAL.md](MANUAL.md) | Excellent for modules/tests; light on caregiver QR / Tailscale / monitoring publisher. |
| Roadmap “Phase 1 checkpoint report” | Still unchecked in README even though val metrics are already published in README — clarify as “metrics in README; formal Phase-1 write-up pending” if needed. |

---

## 7. Figures / artifacts to attach

| Artifact | How to get it |
|----------|----------------|
| Confusion matrix | `python scripts/eval.py --weights runs/detect/kp_v2_4cls/weights/best.pt` → `runs/detect/eval_*/confusion_matrix.png` |
| Architecture mermaid | SERVER_ARCHITECTURE §2 (edit for Tailscale + :8790 before export) |
| Live UI screenshots | Dashboard `/` (monitoring) + `/sessions`; mobile session + QR scan |
| Deploy summary | Jetson `deploy/handoff/DEPLOY_SUMMARY.txt` (redact tokens in the report!) |
| Wire format | TCP_CONTRACT.md examples |

**Never paste** `CAREGIVER_SIGNAL_TOKEN` / `JETSON_SIGNAL_TOKEN` / Wi‑Fi passwords into the report PDF.

---

## 8. Glossary (short)

| Term | Meaning |
|------|---------|
| Tier 0 / 1 / 2 | Dismiss / voice-verify / immediate escalate |
| Scenario A–D | Standard fall / seizure / syncope / false positive (PRD §5) |
| TSSTG | Two-stream ST-GCN action classifier |
| Signaling | Offer/answer/ICE only — **not** video |
| Monitoring | Continuous vitals JSON for dashboard/mobile home |

---

## 9. Checklist before submitting the report

- [ ] Architecture diagram matches **Tailscale + Jetson signaling + :8790 monitoring** (not “cloud-only signaling”)  
- [ ] CV metrics quote **val** mAP50, with test skew caveat  
- [ ] Hardware status: IMU / PPG marked honestly  
- [ ] Contribution table synced with README statuses  
- [ ] Secrets redacted  
- [ ] Future work = README Roadmap open items + §5 above  
- [ ] Lab demo claim backed by `E2E_LAB.md` (done / partial / planned)
