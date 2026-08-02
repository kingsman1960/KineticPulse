import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";
import { MockMonitoringDataSource } from "../lib/monitoring/dataSources";
import type { MonitoringRepository } from "../lib/monitoring/eventStore";
import { handleMonitoringRequest } from "../lib/monitoring/monitoringApiHandler";

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
    const request = new NextRequest("http://localhost/api/monitoring?scenario=normal");

    const response = await handleMonitoringRequest(request, {
      createDataSource: () => new MockMonitoringDataSource(),
      getRepository: () => unavailableRepository
    });

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({ error: "SQLite database is unavailable" });
  });

  it("preserves the normalized public response contract after persistence", async () => {
    const source = new MockMonitoringDataSource();
    const repository: MonitoringRepository = {
      save(model) {
        return model;
      },
      latest() {
        return null;
      }
    };
    const request = new NextRequest("http://localhost/api/monitoring?scenario=normal");
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
