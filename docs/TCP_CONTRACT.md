# Wristband ↔ Jetson TCP contract

NDJSON over TCP. Jetson is the **server** (`wristband.tcp_host:tcp_port`, default `0.0.0.0:5555`). ESP32 is the client.

Parser: [`kineticpulse/sensors/tcp.py`](../kineticpulse/sensors/tcp.py).  
Firmware reference: [`src/main.cpp`](../src/main.cpp).

## Events (one JSON object per line, UTF-8, `\n` terminated)

| `type` | Fields | Notes |
|--------|--------|--------|
| `hello` | `device`, `fw`, `caps[]` | Optional on connect; logged only |
| `hr` | `bpm` (int), `ts` | Pre-computed heart rate |
| `accel` | `ax`,`ay`,`az` (g), `ts` | Required for full Scenario B |
| `ppg` | `ir[]`,`red[]`, `ts` | Raw MAX30102; Jetson derives BPM if `has_ppg_raw: true` |
| `pulse_lost` | `duration_s`, `ts` | Optional cardiac-loss signal |

`ts` is informational — Jetson stamps events with its own clock on receive.

### Examples

```json
{"type":"hello","device":"esp32-kp-001","fw":"0.2.0","caps":["hr","accel"]}
{"type":"hr","bpm":72,"ts":123456}
{"type":"accel","ax":0.10,"ay":0.02,"az":0.99,"ts":123456}
{"type":"ppg","ir":[1234,1235],"red":[1100,1101],"ts":123456}
{"type":"pulse_lost","duration_s":3.0,"ts":123500}
```

**Do not** send a combined envelope like `{"type":"sample","hr":{...},"accel":{...}}` — the Jetson ignores unknown types.

## Reconnect

If the socket drops, firmware must reconnect. Jetson closes idle clients after `wristband.tcp_idle_timeout_s` (default 10s) with no data.

## Config flags (Jetson `config.yaml`)

| Flag | Meaning |
|------|---------|
| `wristband.transport: tcp` | Production path |
| `wristband.has_ppg_raw: true` | Expect `ppg` bursts (else use `hr`) |
| `wristband.has_accelerometer: true` | Flip when real IMU is on the board |

## Bring-up smoke

```bash
# Jetson
./kineticpulse --mock-stt   # or full run; watch logs for TCP connect

# ESP32 (after wifi_secrets.h)
pio run -e seeed_xiao_esp32s3 -t upload && pio device monitor

# Expect on Jetson:
#   TCP: wristband connected from ...
#   TCP: wristband hello device='esp32-kp-001' ...
```

Dashboard (real mode) should show ESP32 connected + changing BPM within a few seconds.
