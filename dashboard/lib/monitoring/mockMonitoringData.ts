import type { MonitoringScenario, MonitoringWirePayload } from "./model";

const NOW_MS = Date.now();

/**
 * Mock field integration contract (applies to every object below):
 *
 * - `system.connection` simulates Jetson/backend liveness. Source: edge runtime
 *   health publisher. Enum: connected/degraded/disconnected; never nullable.
 *   Replace in `BackendMonitoringDataSource.read()` from a future health API.
 * - `sensor.connection` simulates the ESP32 TCP/BLE link. Source: ESP32 sensor
 *   transport. Enum: connected/degraded/disconnected; never nullable. Map from
 *   `TcpSensorServer`/BLE connection lifecycle in the future monitoring publisher.
 * - `snapshot.latest_hr_bpm` simulates heart rate. Source: ESP32/MAX30102 through
 *   `HrSample`. Unit: BPM; expected physiological range 20-240. `null` means no
 *   valid pulse/sample. Replace from `FusionSnapshot.latest_hr_bpm`.
 * - `snapshot.latest_accel_g` and `snapshot.accel` simulate IMU fusion. Source:
 *   ESP32 accelerometer through `AccelSample`. Unit: g; sensor range 0-8 g;
 *   `null` means IMU absent/unavailable. Replace from `FusionSnapshot`.
 * - `snapshot.detector_class`/`detector_conf` simulate the vision pipeline.
 *   Class uses the existing fallen/falling/stand/sitting schema; confidence is
 *   0-1. Both `null` mean no camera result. Replace from `FusionSnapshot`.
 * - `snapshot.action_class`/`action_conf` simulate temporal vision output.
 *   Confidence is 0-1; `null` means no temporal result. Replace from
 *   `FusionSnapshot.action_class/action_conf`.
 * - `snapshot.decision` simulates sensor-fusion output and uses the exact
 *   `EmergencyTier`, scenario, and reason values from `TierDecision`. Replace
 *   from `FusionSnapshot.decision` without renaming fields.
 * - `voice.status` simulates voice verification. Source: voice verification
 *   worker; enum shown in `model.ts`; never nullable. TODO: publish the worker's
 *   pending state and map `VoiceVerdict` in the backend monitoring envelope.
 * - `alert_dispatch.status` simulates webhook delivery. Source: alert dispatcher;
 *   enum idle/pending/sent/failed; never nullable. TODO: expose dispatch outcomes
 *   from `WebhookDispatcher` and map them in the backend monitoring envelope.
 * - `events` simulate cross-pipeline events. Timestamps are Unix milliseconds;
 *   IDs must be unique; event data is bounded by `InMemoryEventStore`. Replace
 *   by backend-published events at the real adapter boundary.
 *
 * All mock and in-memory event data is lost on server restart.
 */

/**
 * Simulates healthy, active monitoring: 72 BPM, stable 1 g motion, standing
 * vision result at 96%, no fall, no voice verification, and no dispatched alert.
 * Sources and integration mapping are defined in the contract above.
 */
const normal: MonitoringWirePayload = {
  subject_id: "resident-001",
  location: "Living room",
  system: { connection: "connected" },
  sensor: { connection: "connected" },
  snapshot: {
    decision: { tier: "none", scenario: "monitoring", reason: "No fall signatures detected." },
    pose: "upright",
    accel: "quiet",
    hr: "resting",
    latest_hr_bpm: 72,
    latest_accel_g: 1.01,
    detector_class: "stand",
    detector_conf: 0.96,
    action_class: "stand",
    action_conf: 0.93,
    timestamp_ms: NOW_MS
  },
  voice: { status: "not_required" },
  alert_dispatch: { status: "idle" },
  events: [
    { id: "normal-heartbeat", timestamp_ms: NOW_MS - 12_000, severity: "info", category: "system", title: "Monitoring active", detail: "Jetson pipeline and sensor transport are healthy." },
    { id: "normal-vision", timestamp_ms: NOW_MS - 34_000, severity: "info", category: "vision", title: "Standing posture", detail: "Vision confidence 96%; no fall signature." },
    { id: "normal-sensor", timestamp_ms: NOW_MS - 61_000, severity: "info", category: "sensor", title: "Sensor sample received", detail: "Heart rate and motion are within normal bounds." }
  ]
};

/**
 * Simulates a resting subject: 61 BPM, gravity-dominant motion, sitting vision
 * at 94%, and no emergency. BPM is valid and not pulse loss. Sources and the
 * exact future replacement points are defined in the contract above.
 */
const resting: MonitoringWirePayload = {
  subject_id: "resident-001",
  location: "Bedroom",
  system: { connection: "connected" },
  sensor: { connection: "connected" },
  snapshot: {
    decision: { tier: "none", scenario: "monitoring", reason: "No fall signatures detected." },
    pose: "upright",
    accel: "quiet",
    hr: "resting",
    latest_hr_bpm: 61,
    latest_accel_g: 0.99,
    detector_class: "sitting",
    detector_conf: 0.94,
    action_class: "sitting",
    action_conf: 0.91,
    timestamp_ms: NOW_MS
  },
  voice: { status: "not_required" },
  alert_dispatch: { status: "idle" },
  events: [
    { id: "resting-state", timestamp_ms: NOW_MS - 9_000, severity: "info", category: "fusion", title: "Resting state", detail: "Stable posture and resting heart-rate signature." },
    { id: "resting-vision", timestamp_ms: NOW_MS - 40_000, severity: "info", category: "vision", title: "Sitting posture", detail: "Camera detection is available with 94% confidence." }
  ]
};

/**
 * Simulates a possible standard fall: elevated 108 BPM, recent 2.8 g impact,
 * falling detection at 76%, Tier 1, and pending voice verification. Confidence
 * values are 0-1 and not nullable here. Sources/mapping follow the contract above.
 */
const possibleFall: MonitoringWirePayload = {
  subject_id: "resident-001",
  location: "Hallway",
  system: { connection: "connected" },
  sensor: { connection: "connected" },
  snapshot: {
    decision: { tier: "tier_1_verify", scenario: "A", reason: "Posture change + impact detected; verifying verbally." },
    pose: "falling",
    accel: "impact_only",
    hr: "panic_spike",
    latest_hr_bpm: 108,
    latest_accel_g: 2.8,
    detector_class: "falling",
    detector_conf: 0.76,
    action_class: "falling",
    action_conf: 0.79,
    timestamp_ms: NOW_MS
  },
  voice: { status: "pending" },
  alert_dispatch: { status: "pending" },
  events: [
    { id: "possible-voice", timestamp_ms: NOW_MS - 1_000, severity: "warning", category: "voice", title: "Voice check started", detail: "Waiting for a clear response from the subject." },
    { id: "possible-tier", timestamp_ms: NOW_MS - 2_000, severity: "warning", category: "fusion", title: "Tier 1 verification", detail: "Posture change and impact require verification." },
    { id: "possible-impact", timestamp_ms: NOW_MS - 3_000, severity: "warning", category: "sensor", title: "Impact detected", detail: "ESP32 IMU magnitude reached 2.8 g." }
  ]
};

/**
 * Simulates a confirmed fall after an unclear/distress voice result: 122 BPM,
 * fallen vision at 97%, Tier 1, and an alert successfully sent. All confidence
 * fields are in 0-1. Sources/mapping follow the shared integration contract.
 */
const confirmedFall: MonitoringWirePayload = {
  subject_id: "resident-001",
  location: "Kitchen",
  system: { connection: "connected" },
  sensor: { connection: "connected" },
  snapshot: {
    decision: { tier: "tier_1_verify", scenario: "A", reason: "Posture change + impact detected; verifying verbally." },
    pose: "prone",
    accel: "impact_only",
    hr: "panic_spike",
    latest_hr_bpm: 122,
    latest_accel_g: 4.7,
    detector_class: "fallen",
    detector_conf: 0.97,
    action_class: "fallen",
    action_conf: 0.95,
    timestamp_ms: NOW_MS
  },
  voice: { status: "distress" },
  alert_dispatch: { status: "sent" },
  events: [
    { id: "confirmed-alert", timestamp_ms: NOW_MS - 500, severity: "critical", category: "alert", title: "Caregiver alert sent", detail: "Fall and distress result were dispatched." },
    { id: "confirmed-voice", timestamp_ms: NOW_MS - 1_400, severity: "critical", category: "voice", title: "Distress detected", detail: "Voice verification did not confirm safety." },
    { id: "confirmed-fall", timestamp_ms: NOW_MS - 2_300, severity: "critical", category: "vision", title: "Fall confirmed", detail: "Fallen posture detected with 97% confidence." }
  ]
};

/**
 * Simulates cardiac emergency Scenario C: no valid BPM (`null` means pulse
 * unavailable after timeout), 1.02 g stable motion, fallen vision at 91%, Tier
 * 2 cardiac, bypassed voice verification, and sent alert. Replace/map exactly
 * at the integration points defined above.
 */
const pulseLost: MonitoringWirePayload = {
  subject_id: "resident-001",
  location: "Bathroom",
  system: { connection: "connected" },
  sensor: { connection: "connected" },
  snapshot: {
    decision: { tier: "tier_2_cardiac", scenario: "C", reason: "Pulse signal lost; suspected cardiac arrest." },
    pose: "prone",
    accel: "quiet",
    hr: "pulse_lost",
    latest_hr_bpm: null,
    latest_accel_g: 1.02,
    detector_class: "fallen",
    detector_conf: 0.91,
    action_class: "fallen",
    action_conf: 0.9,
    timestamp_ms: NOW_MS
  },
  voice: { status: "not_required" },
  alert_dispatch: { status: "sent" },
  events: [
    { id: "pulse-alert", timestamp_ms: NOW_MS - 300, severity: "critical", category: "alert", title: "Critical alert sent", detail: "Cardiac emergency bypassed voice verification." },
    { id: "pulse-tier", timestamp_ms: NOW_MS - 800, severity: "critical", category: "fusion", title: "Tier 2 cardiac", detail: "Fusion classified pulse loss as Scenario C." },
    { id: "pulse-lost", timestamp_ms: NOW_MS - 1_200, severity: "critical", category: "sensor", title: "Pulse signal lost", detail: "No valid pulse was observed for longer than the configured timeout." }
  ]
};

/**
 * Simulates a disconnected ESP32: BPM and acceleration are `null` because no
 * current sensor samples exist; vision still reports standing at 88%; system is
 * degraded but reachable; no emergency is inferred from missing data alone.
 * Replace/map at the sensor connection lifecycle points defined above.
 */
const sensorDisconnected: MonitoringWirePayload = {
  subject_id: "resident-001",
  location: "Living room",
  system: { connection: "degraded" },
  sensor: { connection: "disconnected" },
  snapshot: {
    decision: { tier: "none", scenario: "monitoring", reason: "No fall signatures detected." },
    pose: "upright",
    accel: "unknown",
    hr: "unknown",
    latest_hr_bpm: null,
    latest_accel_g: null,
    detector_class: "stand",
    detector_conf: 0.88,
    action_class: "stand",
    action_conf: 0.84,
    timestamp_ms: NOW_MS
  },
  voice: { status: "not_required" },
  alert_dispatch: { status: "idle" },
  events: [
    { id: "disconnected-link", timestamp_ms: NOW_MS - 700, severity: "warning", category: "sensor", title: "Sensor disconnected", detail: "Waiting for the ESP32 telemetry transport to reconnect." },
    { id: "disconnected-system", timestamp_ms: NOW_MS - 900, severity: "warning", category: "system", title: "Monitoring degraded", detail: "Vision remains available; physiological data is unavailable." }
  ]
};

export const mockMonitoringData: Readonly<Record<MonitoringScenario, MonitoringWirePayload>> = {
  normal,
  resting,
  possible_fall: possibleFall,
  confirmed_fall: confirmedFall,
  pulse_lost: pulseLost,
  sensor_disconnected: sensorDisconnected
};
