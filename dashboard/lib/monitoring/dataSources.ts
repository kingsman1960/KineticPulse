import { mapBackendMonitoringPayload } from "./backendMonitoringAdapter";
import type { MonitoringEventSource } from "./eventStore";
import {
  type MonitoringModel,
  type MonitoringWirePayload
} from "./model";

export interface MonitoringDataSource {
  readonly source: MonitoringEventSource;
  read(): Promise<MonitoringModel>;
}

/**
 * Real HTTP adapter for Jetson `GET /monitoring`
 * (`kineticpulse.monitoring.http.MonitoringPublisher`).
 *
 * Configure `KINETICPULSE_MONITORING_HTTP_URL` when the Jetson is not on the
 * same host as the dashboard.
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
  const endpoint =
    process.env.KINETICPULSE_MONITORING_HTTP_URL ??
    "http://127.0.0.1:8790/monitoring";
  return new BackendMonitoringDataSource(endpoint);
}
