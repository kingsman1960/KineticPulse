import { mapBackendMonitoringPayload } from "./backendMonitoringAdapter";
import { mapMockScenario } from "./mockMonitoringAdapter";
import type { MonitoringEventSource } from "./eventStore";
import {
  DEFAULT_MONITORING_SCENARIO,
  type MonitoringModel,
  type MonitoringScenario,
  type MonitoringWirePayload
} from "./model";

export interface MonitoringDataSource {
  readonly source: MonitoringEventSource;
  read(scenario?: MonitoringScenario): Promise<MonitoringModel>;
}

export class MockMonitoringDataSource implements MonitoringDataSource {
  readonly source = "mock" as const;
  async read(scenario = DEFAULT_MONITORING_SCENARIO): Promise<MonitoringModel> {
    return mapMockScenario(scenario);
  }
}

/**
 * Real HTTP adapter for Jetson `GET /monitoring`
 * (`kineticpulse.monitoring.http.MonitoringPublisher`).
 *
 * Set `MONITORING_DATA_MODE=real` and
 * `KINETICPULSE_MONITORING_HTTP_URL=http://<jetson>:8790/monitoring`.
 */
export class BackendMonitoringDataSource implements MonitoringDataSource {
  readonly source = "jetson" as const;
  constructor(private readonly endpoint: string) {}

  async read(): Promise<MonitoringModel> {
    const response = await fetch(this.endpoint, {
      cache: "no-store",
      headers: { Accept: "application/json" }
    });
    if (!response.ok) throw new Error(`Monitoring backend returned HTTP ${response.status}`);
    const payload = (await response.json()) as MonitoringWirePayload;
    return mapBackendMonitoringPayload(payload);
  }
}

export function createMonitoringDataSource(): MonitoringDataSource {
  const mode = process.env.MONITORING_DATA_MODE ?? "mock";
  if (mode === "mock") return new MockMonitoringDataSource();
  if (mode === "real") {
    const endpoint = process.env.KINETICPULSE_MONITORING_HTTP_URL;
    if (!endpoint) {
      throw new Error("KINETICPULSE_MONITORING_HTTP_URL is required in real monitoring mode");
    }
    return new BackendMonitoringDataSource(endpoint);
  }
  throw new Error(`Unsupported MONITORING_DATA_MODE: ${mode}`);
}
