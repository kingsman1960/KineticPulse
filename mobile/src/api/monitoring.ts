import { AppSettings } from "@/types/session";

export type LiveVitals = {
  bpm: number | null;
  hrStatus: string;
  sensorConnection: string;
  emergencyTier: string;
  scenario: string;
  updatedAtMs: number;
};

function monitoringUrl(settings: AppSettings): string {
  if (settings.monitoringHttpBase?.trim()) {
    return settings.monitoringHttpBase.trim().replace(/\/$/, "");
  }
  try {
    const u = new URL(settings.signalingHttpBase);
    u.port = "8790";
    u.pathname = "/monitoring";
    u.search = "";
    u.hash = "";
    return u.toString().replace(/\/$/, "");
  } catch {
    return "http://localhost:8790/monitoring";
  }
}

/** Poll Jetson GET /monitoring for continuous vitals (same contract as dashboard). */
export async function fetchLiveVitals(settings: AppSettings): Promise<LiveVitals> {
  const url = monitoringUrl(settings);
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`Monitoring HTTP ${response.status}`);
  const json = await response.json();
  const snap = json.snapshot ?? {};
  const hr = snap.latest_hr_bpm;
  let hrStatus = "unavailable";
  if (json.sensor?.connection === "disconnected") hrStatus = "unavailable";
  else if (snap.hr === "pulse_lost") hrStatus = "pulse_lost";
  else if (typeof hr === "number") {
    if (hr < 50) hrStatus = "low";
    else if (hr > 100) hrStatus = "elevated";
    else hrStatus = "normal";
  }
  return {
    bpm: typeof hr === "number" ? hr : null,
    hrStatus,
    sensorConnection: json.sensor?.connection ?? "unknown",
    emergencyTier: snap.decision?.tier ?? "none",
    scenario: snap.decision?.scenario ?? "",
    updatedAtMs: snap.timestamp_ms ?? Date.now()
  };
}
