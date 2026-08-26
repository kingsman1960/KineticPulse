import type { MonitoringWirePayload } from "../lib/monitoring/model";

export function normalMonitoringPayload(): MonitoringWirePayload {
  const now = Date.now();
  return {
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
      timestamp_ms: now
    },
    voice: { status: "not_required" },
    alert_dispatch: { status: "idle" },
    events: [
      { id: "runtime-2", timestamp_ms: now - 1_000, severity: "info", category: "vision", title: "Standing posture", detail: "Vision confidence 96%; no fall signature." },
      { id: "runtime-1", timestamp_ms: now - 2_000, severity: "info", category: "sensor", title: "Sensor sample received", detail: "Heart rate and motion are within normal bounds." }
    ]
  };
}

export function disconnectedMonitoringPayload(): MonitoringWirePayload {
  const payload = normalMonitoringPayload();
  payload.system.connection = "degraded";
  payload.sensor.connection = "disconnected";
  payload.snapshot.accel = "unknown";
  payload.snapshot.hr = "unknown";
  payload.snapshot.latest_hr_bpm = null;
  payload.snapshot.latest_accel_g = null;
  payload.events = [];
  return payload;
}

export function pulseLostMonitoringPayload(): MonitoringWirePayload {
  const payload = normalMonitoringPayload();
  payload.snapshot.decision = {
    tier: "tier_2_cardiac",
    scenario: "C",
    reason: "Pulse signal lost; suspected cardiac arrest."
  };
  payload.snapshot.pose = "prone";
  payload.snapshot.hr = "pulse_lost";
  payload.snapshot.latest_hr_bpm = null;
  payload.snapshot.detector_class = "fallen";
  payload.snapshot.detector_conf = 0.91;
  payload.voice.status = "not_required";
  payload.alert_dispatch.status = "sent";
  payload.events = [];
  return payload;
}
