# KineticPulse ESP32 TCP Telemetry Contract

This document defines the hardware/software contract between the ESP32
wristband firmware and the KineticPulse runtime.

The current production telemetry path is TCP/Wi-Fi. The Jetson or
developer laptop runs `TcpSensorServer`; the ESP32 connects as a TCP
client and sends newline-delimited UTF-8 JSON.

## Roles

| Side | Responsibility |
|---|---|
| Jetson/laptop software | Listen on `wristband.tcp_host:wristband.tcp_port`, parse JSON lines, timestamp received events with Jetson monotonic time, feed `SensorEvent`s into fusion. |
| ESP32 firmware | Connect to the configured host/port, send one JSON object per line, reconnect when disconnected, keep event units and field names exactly as specified here. |

## Connection

Default software settings:

```yaml
wristband:
  transport: tcp
  tcp_host: "0.0.0.0"
  tcp_port: 5555
  tcp_idle_timeout_s: 10.0
  tcp_max_line_bytes: 65536
  has_accelerometer: false
  has_ppg_raw: true
  ppg_sample_rate_hz: 100
```

Firmware requirements:

- The ESP32 opens a TCP client connection to `<jetson-ip>:5555` unless the team configures a different port.
- Each event is encoded as a single UTF-8 JSON object followed by `\n`.
- Do not send multiple JSON objects on one line.
- Do not send non-JSON text after connection, except during local debugging with software team agreement.
- If the server closes the socket, the ESP32 reconnects automatically.
- After reconnect, the ESP32 should send a fresh `hello` event.
- The ESP32 should keep sending data often enough that the server is not idle for `tcp_idle_timeout_s` seconds. Any valid line counts as activity.

## Timestamp Rule

Every event may include a firmware-side `ts` field, but software treats it
as informational only.

The Jetson timestamps events when they are received. This keeps fusion
timing consistent across TCP, BLE fallback, and mock sources.

Recommended firmware `ts` format:

- integer milliseconds since ESP32 boot, or
- integer Unix milliseconds if firmware already has reliable wall-clock sync.

The software currently does not depend on either choice.

## Required Event Types

### 1. Hello

Sent once immediately after connection and again after every reconnect.

```json
{"type":"hello","device":"esp32-kp-001","fw":"0.1.0","caps":["hr","accel","ppg"]}
```

Fields:

| Field | Type | Required | Meaning |
|---|---:|---:|---|
| `type` | string | yes | Must be `"hello"`. |
| `device` | string | yes | Stable device identifier. |
| `fw` | string | yes | Firmware version. |
| `caps` | array of strings | yes | Capabilities the device can send. Known values: `"hr"`, `"accel"`, `"ppg"`. |

Software behavior:

- Logs the handshake.
- Does not emit a fusion event.

### 2. Computed Heart Rate

Use this event when the ESP32 sends computed BPM directly.

```json
{"type":"hr","bpm":72,"ts":1758291234567}
```

Fields:

| Field | Type | Required | Unit |
|---|---:|---:|---|
| `type` | string | yes | Must be `"hr"`. |
| `bpm` | integer | yes | beats per minute |
| `ts` | integer | recommended | firmware timestamp, informational |

Expected cadence:

- Recommended: 1 Hz.
- Minimum for responsive fusion: at least once every 2 seconds when available.

Software behavior:

- Converts to `HrSample`.
- Fusion uses recent HR values to identify resting, panic spike, seizure spike, bradycardia, and pulse-loss contexts.

### 3. Accelerometer

Use this event when the IMU is available.

```json
{"type":"accel","ax":0.10,"ay":0.02,"az":0.99,"ts":1758291234580}
```

Fields:

| Field | Type | Required | Unit |
|---|---:|---:|---|
| `type` | string | yes | Must be `"accel"`. |
| `ax` | number | yes | g |
| `ay` | number | yes | g |
| `az` | number | yes | g |
| `ts` | integer | recommended | firmware timestamp, informational |

Unit requirement:

- Acceleration values must be in `g`, not raw ADC counts and not `m/s^2`.
- At rest, magnitude should be close to `1.0 g`.

Expected cadence:

- Recommended: 25-50 Hz over TCP.
- If firmware samples faster internally, it may downsample before sending.

Software behavior:

- Converts to `AccelSample`.
- Fusion detects impact, stillness, soft collapse, and impact-plus-tremor signatures from recent samples.

### 4. Raw PPG Burst

Use this event when the ESP32 streams raw MAX30102 samples and the Jetson
computes BPM.

```json
{"type":"ppg","ir":[1234,1235,1236],"red":[1100,1101,1102],"ts":1758291234590}
```

Fields:

| Field | Type | Required | Unit |
|---|---:|---:|---|
| `type` | string | yes | Must be `"ppg"`. |
| `ir` | array of integers | yes | raw MAX30102 IR samples |
| `red` | array of integers | yes | raw MAX30102 red samples |
| `ts` | integer | recommended | timestamp of the last sample in the burst, informational |

Array requirements:

- `len(ir)` and `len(red)` must be equal.
- Arrays must contain samples in chronological order.
- Values should be raw unsigned sensor readings, not normalized floats.
- Keep each JSON line under `tcp_max_line_bytes` bytes. Current default max is 65,536 bytes.

Expected cadence:

- Default software assumption: `ppg_sample_rate_hz: 100`.
- Recommended burst size: 10-25 samples per message at 100 Hz.
- If hardware uses 50 Hz or 200 Hz, software config must be updated before demo.

Software behavior:

- Feeds samples to `PpgProcessor`.
- Emits `HrSample` internally when enough PPG history exists to estimate BPM.
- If `wristband.has_ppg_raw` is `false`, raw PPG events are ignored.

### 5. Pulse Lost

Use this event when firmware is confident that the optical pulse signal is
absent or invalid for a continuous period.

```json
{"type":"pulse_lost","duration_s":3.0,"ts":1758291235000}
```

Fields:

| Field | Type | Required | Unit |
|---|---:|---:|---|
| `type` | string | yes | Must be `"pulse_lost"`. |
| `duration_s` | number | yes | seconds |
| `ts` | integer | recommended | firmware timestamp, informational |

Software behavior:

- Converts to `PulseLost`.
- Fusion classifies pulse loss at or above `thresholds.pulse_loss_timeout_s` as Tier 2 cardiac emergency.

## Current Capability Flags

The software uses capability flags in `config.yaml` to describe the
current hardware build:

```yaml
wristband:
  has_accelerometer: false
  has_ppg_raw: true
```

Hardware/software agreement:

- Set `has_accelerometer: true` only when the IMU is physically present and firmware sends valid `accel` events.
- Set `has_ppg_raw: true` when firmware sends raw `ppg` bursts.
- Set `has_ppg_raw: false` when firmware sends computed `hr` BPM values instead.

## Error Handling

Software currently behaves as follows:

| Input problem | Software behavior |
|---|---|
| malformed JSON line | log warning, keep connection open |
| unknown `type` | ignore at debug level |
| invalid/missing required fields | drop that event |
| oversized line | ignore or close depending on size path |
| idle connection | close after `tcp_idle_timeout_s`; firmware should reconnect |
| second client connects | new connection replaces previous connection |

Firmware should prefer dropping bad local samples over sending malformed
events.

## Minimal Firmware Send Loop

Pseudocode:

```text
connect to <jetson-ip>:5555
send hello

while connected:
    if computed HR available:
        send {"type":"hr","bpm":..., "ts":...}

    if IMU available:
        send {"type":"accel","ax":..., "ay":..., "az":..., "ts":...}

    if raw PPG enabled:
        send {"type":"ppg","ir":[...],"red":[...],"ts":...}

    if pulse has been absent for duration_s:
        send {"type":"pulse_lost","duration_s":duration_s,"ts":...}

on disconnect:
    wait briefly
    reconnect
    send hello again
```

## Hardware Team Confirmation Checklist

Please confirm these before Phase 3 real ESP32 integration:

| Question | Hardware answer |
|---|---|
| Will firmware connect to Jetson/laptop TCP port `5555`? | TBD |
| Will firmware send newline-delimited UTF-8 JSON exactly as specified here? | TBD |
| Will HR be computed BPM (`hr`) or raw PPG (`ppg`) for the first integration? | TBD |
| If raw PPG: what is the MAX30102 sample rate? | TBD |
| If raw PPG: how many samples per burst will firmware send? | TBD |
| Is an accelerometer available for the first hardware test? | TBD |
| If accelerometer is available: are `ax`, `ay`, `az` sent in `g`? | TBD |
| What accelerometer output rate will firmware send over TCP? | TBD |
| What reconnect/backoff behavior will ESP32 implement? | TBD |
| Will firmware send `pulse_lost`, or should Jetson infer pulse loss only from missing/invalid PPG? | TBD |
| Will firmware include battery level or device health in a later event type? | TBD |

## Phase 3 Acceptance Criteria

The real ESP32 integration is accepted when:

- Runtime logs `TCP: wristband connected`.
- Runtime logs the `hello` device and firmware version.
- HR or PPG data reaches the software without parser warnings.
- If IMU is present, accelerometer events reach software and resting magnitude is near `1.0 g`.
- Disconnect/reconnect works at least once.
- No changes are needed outside `sensors/tcp.py`, `sensors/parser.py`, `sensors/ppg.py`, or config unless the team explicitly changes the contract.
