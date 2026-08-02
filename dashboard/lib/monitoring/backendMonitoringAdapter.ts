import type {
  HeartRateStatus,
  MonitoringModel,
  MonitoringWirePayload,
  MotionState,
  VisionState
} from "./model";

function heartRateStatus(payload: MonitoringWirePayload): HeartRateStatus {
  if (payload.sensor.connection === "disconnected") return "unavailable";
  if (payload.snapshot.hr === "pulse_lost") return "pulse_lost";
  const bpm = payload.snapshot.latest_hr_bpm;
  if (bpm === null) return "unavailable";
  if (bpm < 50) return "low";
  if (bpm > 100) return "elevated";
  return "normal";
}

function motionState(accel: string, magnitudeG: number | null): MotionState {
  if (magnitudeG === null || accel === "unknown") return "unknown";
  if (accel === "impact_tremor") return "tremor";
  if (accel === "impact_only" || accel === "soft_collapse") return "impact";
  return magnitudeG < 1.05 ? "resting" : "stable";
}

function visionState(value: VisionState | null): VisionState {
  return value ?? "no_result";
}

function fallConfidence(payload: MonitoringWirePayload): number | null {
  const { detector_class, detector_conf, action_class, action_conf } = payload.snapshot;
  const fallClass = detector_class === "fallen" || detector_class === "falling";
  const fallAction = action_class === "fallen" || action_class === "falling";
  if (!fallClass && !fallAction) return detector_class === null && action_class === null ? null : 0;
  return Math.max(fallClass ? detector_conf ?? 0 : 0, fallAction ? action_conf ?? 0 : 0);
}

/**
 * Maps the monitoring wire envelope to the UI's normalized model. Existing
 * Python field names terminate here; components never depend on backend shape.
 */
export function mapBackendMonitoringPayload(payload: MonitoringWirePayload): MonitoringModel {
  const confidence = fallConfidence(payload);
  const emergency = payload.snapshot.decision.tier;
  const fallDetected =
    confidence !== null &&
    confidence > 0 &&
    emergency !== "none" &&
    emergency !== "tier_0_dismiss";

  return {
    subjectId: payload.subject_id,
    location: payload.location,
    updatedAtMs: payload.snapshot.timestamp_ms,
    system: {
      connection: payload.system.connection,
      label: payload.system.connection === "connected" ? "System online" : payload.system.connection === "degraded" ? "System degraded" : "System offline"
    },
    sensor: {
      connection: payload.sensor.connection,
      label: payload.sensor.connection === "connected" ? "ESP32 connected" : payload.sensor.connection === "degraded" ? "ESP32 degraded" : "ESP32 disconnected"
    },
    heartRate: {
      bpm: payload.snapshot.latest_hr_bpm,
      status: heartRateStatus(payload)
    },
    motion: {
      state: motionState(payload.snapshot.accel, payload.snapshot.latest_accel_g),
      magnitudeG: payload.snapshot.latest_accel_g
    },
    vision: {
      state: visionState(payload.snapshot.detector_class),
      confidence: payload.snapshot.detector_conf,
      actionClass: payload.snapshot.action_class
    },
    fall: { confidence, detected: fallDetected },
    emergency: {
      level: emergency,
      scenario: payload.snapshot.decision.scenario,
      reason: payload.snapshot.decision.reason
    },
    voiceVerification: { status: payload.voice.status },
    alertDispatch: { status: payload.alert_dispatch.status },
    recentEvents: payload.events
      .map((event) => ({
        id: event.id,
        timestampMs: event.timestamp_ms,
        severity: event.severity,
        category: event.category,
        title: event.title,
        detail: event.detail
      }))
      .sort((a, b) => b.timestampMs - a.timestampMs)
  };
}
