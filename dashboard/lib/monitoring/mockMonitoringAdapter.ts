import { mapBackendMonitoringPayload } from "./backendMonitoringAdapter";
import { mockMonitoringData } from "./mockMonitoringData";
import type { MonitoringModel, MonitoringScenario } from "./model";

/** Separate mock adapter: UI code does not import or understand mock objects. */
export function mapMockScenario(scenario: MonitoringScenario): MonitoringModel {
  const model = mapBackendMonitoringPayload(mockMonitoringData[scenario]);
  return { ...model, updatedAtMs: Date.now() };
}
