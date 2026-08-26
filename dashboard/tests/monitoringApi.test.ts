import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";
import { mapBackendMonitoringPayload } from "../lib/monitoring/backendMonitoringAdapter";
import type { MonitoringDataSource } from "../lib/monitoring/dataSources";
import type { MonitoringRepository } from "../lib/monitoring/eventStore";
import { handleMonitoringRequest } from "../lib/monitoring/monitoringApiHandler";
import { normalMonitoringPayload } from "./monitoringFixture";

function realDataSource(): MonitoringDataSource {
  return {
    source: "jetson",
    async read() {
      return mapBackendMonitoringPayload(normalMonitoringPayload());
    }
  };
}

describe("monitoring API persistence failures", () => {
  it("returns HTTP 503 instead of crashing when SQLite is unavailable", async () => {
    const unavailableRepository: MonitoringRepository = {
      save() {
        throw new Error("SQLite database is unavailable");
      },
      latest() {
        return null;
      }
    };
    const request = new NextRequest("http://localhost/api/monitoring");

    const response = await handleMonitoringRequest(request, {
      createDataSource: realDataSource,
      getRepository: () => unavailableRepository
    });

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({ error: "SQLite database is unavailable" });
  });

  it("preserves the normalized public response contract after persistence", async () => {
    const source = realDataSource();
    const repository: MonitoringRepository = {
      save(model) {
        return model;
      },
      latest() {
        return null;
      }
    };
    const request = new NextRequest("http://localhost/api/monitoring");
    const response = await handleMonitoringRequest(request, {
      createDataSource: () => source,
      getRepository: () => repository
    });
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toMatchObject({ subjectId: "resident-001", heartRate: { bpm: 72 }, recentEvents: expect.any(Array) });
    expect(body).not.toHaveProperty("source");
  });
});
