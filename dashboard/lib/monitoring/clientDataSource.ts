import type { MonitoringModel, MonitoringScenario } from "./model";

/** Browser polling boundary; replace its implementation with WebSocket later. */
export async function fetchMonitoringSnapshot(
  scenario: MonitoringScenario,
  signal?: AbortSignal
): Promise<MonitoringModel> {
  const query = new URLSearchParams({ scenario });
  const response = await fetch(`/api/monitoring?${query}`, {
    cache: "no-store",
    signal,
    headers: { Accept: "application/json" }
  });
  if (!response.ok) {
    throw new Error(response.status === 503 ? "Monitoring backend unavailable" : `Monitoring request failed (HTTP ${response.status})`);
  }
  return (await response.json()) as MonitoringModel;
}
