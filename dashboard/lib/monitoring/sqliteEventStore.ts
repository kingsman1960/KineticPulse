import Database from "better-sqlite3";
import { mkdirSync } from "node:fs";
import path from "node:path";
import type {
  EventPersistenceContext,
  EventStore,
  MonitoringEventSource
} from "./eventStore";
import type { MonitoringEvent, MonitoringModel, MonitoringSeverity } from "./model";
import { SQLITE_MIGRATIONS, type SQLiteMigration } from "./sqliteMigrations";

type DatabaseConnection = InstanceType<typeof Database>;

interface MonitoringEventRow {
  source_event_id: string;
  event_timestamp_utc: string;
  severity: MonitoringSeverity;
  event_type: MonitoringEvent["category"];
  title: string;
  detail: string;
}

interface InsertRow {
  id: string;
  source_event_id: string;
  source: MonitoringEventSource;
  event_timestamp_utc: string;
  event_type: MonitoringEvent["category"];
  scenario_type: string;
  severity: MonitoringSeverity;
  title: string;
  detail: string;
  system_status: string;
  device_connection_status: string;
  heart_rate_bpm: number | null;
  imu_state: string;
  vision_state: string;
  fall_confidence: number | null;
  fall_detected: number;
  emergency_tier: string;
  voice_verification_status: string;
  alert_dispatch_status: string;
  normalized_payload_json: string | null;
  created_at_utc: string;
}

export interface SQLiteEventStoreOptions {
  dbPath: string;
  recentLimit?: number;
  retentionDays?: number;
  now?: () => Date;
}

const CREATE_MIGRATION_TABLE = `CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  description TEXT NOT NULL,
  applied_at_utc TEXT NOT NULL
)`;

const INSERT_EVENT_SQL = `INSERT INTO monitoring_events (
  id,
  source_event_id,
  source,
  event_timestamp_utc,
  event_type,
  scenario_type,
  severity,
  title,
  detail,
  system_status,
  device_connection_status,
  heart_rate_bpm,
  imu_state,
  vision_state,
  fall_confidence,
  fall_detected,
  emergency_tier,
  voice_verification_status,
  alert_dispatch_status,
  normalized_payload_json,
  created_at_utc
) VALUES (
  @id,
  @source_event_id,
  @source,
  @event_timestamp_utc,
  @event_type,
  @scenario_type,
  @severity,
  @title,
  @detail,
  @system_status,
  @device_connection_status,
  @heart_rate_bpm,
  @imu_state,
  @vision_state,
  @fall_confidence,
  @fall_detected,
  @emergency_tier,
  @voice_verification_status,
  @alert_dispatch_status,
  @normalized_payload_json,
  @created_at_utc
) ON CONFLICT DO NOTHING`;

/**
 * SQLite-backed operational event history. This module is imported only from
 * the Node.js route handler and is externalized from Next.js client bundles.
 */
export class SQLiteEventStore implements EventStore {
  private readonly db: DatabaseConnection;
  private readonly recentLimit: number;
  private readonly retentionDays: number;
  private readonly now: () => Date;

  constructor(options: SQLiteEventStoreOptions) {
    this.recentLimit = options.recentLimit ?? 30;
    this.retentionDays = options.retentionDays ?? 30;
    this.now = options.now ?? (() => new Date());
    if (this.recentLimit <= 0 || this.retentionDays <= 0) {
      throw new Error("SQLite event limit and retention days must be positive");
    }

    if (options.dbPath !== ":memory:") {
      mkdirSync(path.dirname(options.dbPath), { recursive: true });
    }
    this.db = new Database(options.dbPath);
    this.configureConnection();
    this.initializeSchema();
    this.cleanupByRetentionPolicy();
  }

  private configureConnection(): void {
    this.db.pragma("foreign_keys = ON");
    this.db.pragma("busy_timeout = 5000");
    this.db.pragma("journal_mode = WAL");
    this.db.pragma("synchronous = NORMAL");
  }

  private initializeSchema(): void {
    this.db.exec(CREATE_MIGRATION_TABLE);
    const appliedRows = this.db.prepare("SELECT version FROM schema_migrations").all() as Array<{ version: number }>;
    const applied = new Set(appliedRows.map((row) => row.version));
    for (const migration of SQLITE_MIGRATIONS) {
      if (!applied.has(migration.version)) this.applyMigration(migration);
    }
    this.db.pragma("optimize");
  }

  private applyMigration(migration: SQLiteMigration): void {
    const run = this.db.transaction(() => {
      for (const statement of migration.statements) this.db.exec(statement);
      this.db.prepare(
        "INSERT INTO schema_migrations(version, description, applied_at_utc) VALUES (?, ?, ?)"
      ).run(migration.version, migration.description, this.now().toISOString());
    });
    run();
  }

  add(events: MonitoringEvent[], context: EventPersistenceContext): MonitoringEvent[] {
    const insert = this.db.prepare(INSERT_EVENT_SQL);
    const payloadJson = JSON.stringify(context.model);
    const createdAtUtc = this.now().toISOString();
    const persist = this.db.transaction((items: MonitoringEvent[]) => {
      for (const event of items) {
        insert.run(this.toInsertRow(event, context.source, context.model, payloadJson, createdAtUtc));
      }
    });
    persist(events);
    return this.list(this.recentLimit);
  }

  private toInsertRow(
    event: MonitoringEvent,
    source: MonitoringEventSource,
    model: MonitoringModel,
    payloadJson: string,
    createdAtUtc: string
  ): InsertRow {
    if (typeof event.id !== "string" || event.id.trim() === "") {
      throw new Error("Monitoring source event ID must be a non-empty string");
    }
    const eventDate = new Date(event.timestampMs);
    if (!Number.isFinite(eventDate.getTime())) {
      throw new Error(`Event ${event.id} has an invalid timestamp`);
    }
    return {
      // Stable source-aware ID is also the deterministic polling deduplication key.
      id: `${source}:${event.id}`,
      source_event_id: event.id,
      source,
      event_timestamp_utc: eventDate.toISOString(),
      event_type: event.category,
      scenario_type: model.emergency.scenario,
      severity: event.severity,
      title: event.title,
      detail: event.detail,
      system_status: model.system.connection,
      device_connection_status: model.sensor.connection,
      heart_rate_bpm: model.heartRate.bpm,
      imu_state: model.motion.state,
      vision_state: model.vision.state,
      fall_confidence: model.fall.confidence,
      fall_detected: model.fall.detected ? 1 : 0,
      emergency_tier: model.emergency.level,
      voice_verification_status: model.voiceVerification.status,
      alert_dispatch_status: model.alertDispatch.status,
      normalized_payload_json: payloadJson,
      created_at_utc: createdAtUtc
    };
  }

  list(limit = this.recentLimit): MonitoringEvent[] {
    if (!Number.isInteger(limit) || limit <= 0) throw new Error("Event list limit must be a positive integer");
    const rows = this.db.prepare(
      `SELECT source_event_id, event_timestamp_utc, severity, event_type, title, detail
       FROM monitoring_events
       ORDER BY event_timestamp_utc DESC, id ASC
       LIMIT ?`
    ).all(limit) as MonitoringEventRow[];
    return rows.map((row) => ({
      id: row.source_event_id,
      timestampMs: Date.parse(row.event_timestamp_utc),
      severity: row.severity,
      category: row.event_type,
      title: row.title,
      detail: row.detail
    }));
  }

  cleanupOlderThan(cutoffUtcIso: string): number {
    const cutoff = new Date(cutoffUtcIso);
    if (!Number.isFinite(cutoff.getTime()) || cutoff.toISOString() !== cutoffUtcIso) {
      throw new Error("Retention cutoff must be a canonical UTC ISO-8601 timestamp");
    }
    const result = this.db.prepare(
      "DELETE FROM monitoring_events WHERE event_timestamp_utc < ?"
    ).run(cutoffUtcIso);
    return result.changes;
  }

  /** Explicit startup retention policy; never called for each polling request. */
  cleanupByRetentionPolicy(): number {
    const cutoffMs = this.now().getTime() - this.retentionDays * 24 * 60 * 60 * 1000;
    return this.cleanupOlderThan(new Date(cutoffMs).toISOString());
  }

  close(): void {
    if (this.db.open) this.db.close();
  }
}
