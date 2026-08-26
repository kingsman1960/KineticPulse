import Database from "better-sqlite3";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import type { EventPersistenceContext } from "../lib/monitoring/eventStore";
import { mapBackendMonitoringPayload } from "../lib/monitoring/backendMonitoringAdapter";
import type { MonitoringEvent, MonitoringModel } from "../lib/monitoring/model";
import { SQLiteEventStore } from "../lib/monitoring/sqliteEventStore";
import { normalMonitoringPayload } from "./monitoringFixture";

const tempDirectories: string[] = [];
const openStores: SQLiteEventStore[] = [];

function tempDatabasePath(): string {
  const directory = mkdtempSync(path.join(tmpdir(), "kineticpulse-sqlite-"));
  tempDirectories.push(directory);
  return path.join(directory, "monitoring.db");
}

function createStore(
  dbPath: string,
  overrides: Partial<ConstructorParameters<typeof SQLiteEventStore>[0]> = {}
): SQLiteEventStore {
  const store = new SQLiteEventStore({ dbPath, recentLimit: 30, retentionDays: 30, ...overrides });
  openStores.push(store);
  return store;
}

function context(model: MonitoringModel = mapBackendMonitoringPayload(normalMonitoringPayload())): EventPersistenceContext {
  return { source: "jetson", model };
}

function event(id: string, timestampMs: number): MonitoringEvent {
  return {
    id,
    timestampMs,
    severity: "info",
    category: "system",
    title: id,
    detail: `event ${id}`
  };
}

afterEach(() => {
  for (const store of openStores.splice(0)) store.close();
  for (const directory of tempDirectories.splice(0)) {
    rmSync(directory, { recursive: true, force: true });
  }
});

describe("SQLiteEventStore", () => {
  it("initializes the schema, migration ledger, and timestamp index", () => {
    const dbPath = tempDatabasePath();
    createStore(dbPath);
    const db = new Database(dbPath, { readonly: true });
    try {
      const tables = db.prepare(
        "SELECT name FROM sqlite_schema WHERE type = 'table' ORDER BY name"
      ).all() as Array<{ name: string }>;
      const indexes = db.prepare(
        "SELECT name FROM sqlite_schema WHERE type = 'index' ORDER BY name"
      ).all() as Array<{ name: string }>;
      const migration = db.prepare("SELECT MAX(version) AS version FROM schema_migrations").get() as { version: number };

      expect(tables.map((row) => row.name)).toContain("monitoring_events");
      expect(migration.version).toBe(2);
      expect(indexes.map((row) => row.name)).toContain("idx_monitoring_events_timestamp_utc");
    } finally {
      db.close();
    }
  });

  it("inserts and retrieves events in descending timestamp order", () => {
    const store = createStore(tempDatabasePath());
    store.add([event("older", 1_700_000_000_000), event("newer", 1_700_000_010_000)], context());

    expect(store.list().map((item) => item.id)).toEqual(["newer", "older"]);
  });

  it("persists events across store re-instantiation", () => {
    const dbPath = tempDatabasePath();
    const first = createStore(dbPath);
    first.add([event("durable", Date.now())], context());
    first.close();
    openStores.splice(openStores.indexOf(first), 1);

    const second = createStore(dbPath);
    expect(second.list().map((item) => item.id)).toEqual(["durable"]);
  });

  it("deduplicates repeated polling by source and stable event ID", () => {
    const dbPath = tempDatabasePath();
    const store = createStore(dbPath);
    const repeated = event("same-source-id", Date.now());
    store.add([repeated], context());
    store.add([repeated], context());

    expect(store.list()).toHaveLength(1);
    const db = new Database(dbPath);
    try {
      const row = db.prepare("SELECT id, source, source_event_id FROM monitoring_events").get() as {
        id: string;
        source: string;
        source_event_id: string;
      };
      expect(row).toEqual({ id: "jetson:same-source-id", source: "jetson", source_event_id: "same-source-id" });

      expect(() => db.prepare(
        `INSERT INTO monitoring_events
         SELECT 'different-primary-id', source_event_id, source, event_timestamp_utc, event_type,
                scenario_type, severity, title, detail, system_status, device_connection_status,
                heart_rate_bpm, imu_state, vision_state, fall_confidence, fall_detected,
                emergency_tier, voice_verification_status, alert_dispatch_status,
                normalized_payload_json, created_at_utc FROM monitoring_events LIMIT 1`
      ).run()).toThrow(/UNIQUE constraint failed: monitoring_events\.source, monitoring_events\.source_event_id/);
    } finally {
      db.close();
    }
  });

  it("rejects non-Jetson event sources at the database boundary", () => {
    const dbPath = tempDatabasePath();
    const store = createStore(dbPath);
    store.add([event("real-event", Date.now())], context());

    const db = new Database(dbPath);
    try {
      expect(() => db.prepare(
        "UPDATE monitoring_events SET source = 'mock' WHERE source_event_id = 'real-event'"
      ).run()).toThrow(/CHECK constraint failed/);
    } finally {
      db.close();
    }
  });

  it("rejects a blank source event ID allowed by the string-only normalized type", () => {
    const store = createStore(tempDatabasePath());

    expect(() => store.add([event("   ", Date.now())], context())).toThrow(
      "Monitoring source event ID must be a non-empty string"
    );
    expect(store.list()).toHaveLength(0);
  });

  it("applies configured age retention once when a store opens", () => {
    const dbPath = tempDatabasePath();
    const now = new Date("2026-08-02T12:00:00.000Z");
    const initial = createStore(dbPath, { retentionDays: 10_000, now: () => now });
    initial.add(
      [
        event("expired", Date.parse("2026-06-01T00:00:00.000Z")),
        event("retained", Date.parse("2026-08-01T00:00:00.000Z"))
      ],
      context()
    );
    initial.close();
    openStores.splice(openStores.indexOf(initial), 1);

    const retained = createStore(dbPath, { retentionDays: 30, now: () => now });
    expect(retained.list().map((item) => item.id)).toEqual(["retained"]);
  });
});
