import type { MonitoringModel } from "./model";

/** Browser polling boundary; replace its implementation with WebSocket later. */
export async function fetchMonitoringSnapshot(
  signal?: AbortSignal
): Promise<MonitoringModel> {
  const response = await fetch("/api/monitoring", {
    cache: "no-store",
    signal,
    headers: { Accept: "application/json" }
  });
  if (!response.ok) {
    throw new Error(response.status === 503 ? "Monitoring backend unavailable" : `Monitoring request failed (HTTP ${response.status})`);
  }
  return (await response.json()) as MonitoringModel;
}
