export type EmergencyLevel =
  | "none"
  | "tier_0_dismiss"
  | "tier_1_verify"
  | "tier_2_seizure"
  | "tier_2_cardiac";

export type ConnectionStatus = "connected" | "degraded" | "disconnected";
export type HeartRateStatus = "normal" | "elevated" | "low" | "pulse_lost" | "unavailable";
export type MotionState = "stable" | "resting" | "impact" | "tremor" | "unknown";
export type VisionState = "stand" | "sitting" | "falling" | "fallen" | "no_result";
export type VoiceVerificationStatus = "not_required" | "pending" | "safe" | "distress" | "unknown";
export type AlertDispatchStatus = "idle" | "pending" | "sent" | "failed";
export type MonitoringSeverity = "info" | "warning" | "critical";

export interface MonitoringEvent {
  id: string;
  timestampMs: number;
  severity: MonitoringSeverity;
  category: "system" | "sensor" | "vision" | "fusion" | "voice" | "alert";
  title: string;
  detail: string;
}

/** The single normalized read model consumed by all dashboard components. */
export interface MonitoringModel {
  subjectId: string;
  location: string;
  updatedAtMs: number;
  system: {
    connection: ConnectionStatus;
    label: string;
  };
  sensor: {
    connection: ConnectionStatus;
    label: string;
  };
  heartRate: {
    bpm: number | null;
    status: HeartRateStatus;
  };
  motion: {
    state: MotionState;
    magnitudeG: number | null;
  };
  vision: {
    state: VisionState;
    confidence: number | null;
    actionClass: string | null;
  };
  fall: {
    confidence: number | null;
    detected: boolean;
  };
  emergency: {
    level: EmergencyLevel;
    scenario: string;
    reason: string;
  };
  voiceVerification: {
    status: VoiceVerificationStatus;
  };
  alertDispatch: {
    status: AlertDispatchStatus;
  };
  recentEvents: MonitoringEvent[];
}

/**
 * Wire contract expected by the real-data adapter. Snapshot field names mirror
 * `kineticpulse.fusion.engine.FusionSnapshot`. Published by Jetson
 * `kineticpulse.monitoring.http.MonitoringPublisher` at GET /monitoring.
 */
export interface MonitoringWirePayload {
  subject_id: string;
  location: string;
  system: { connection: ConnectionStatus };
  sensor: { connection: ConnectionStatus };
  snapshot: {
    decision: { tier: EmergencyLevel; scenario: string; reason: string };
    pose: string;
    accel: string;
    hr: string;
    latest_hr_bpm: number | null;
    latest_accel_g: number | null;
    detector_class: VisionState | null;
    detector_conf: number | null;
    action_class: string | null;
    action_conf: number | null;
    timestamp_ms: number;
  };
  voice: { status: VoiceVerificationStatus };
  alert_dispatch: { status: AlertDispatchStatus };
  events: Array<{
    id: string;
    timestamp_ms: number;
    severity: MonitoringSeverity;
    category: MonitoringEvent["category"];
    title: string;
    detail: string;
  }>;
}
