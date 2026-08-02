export interface SQLiteMigration {
  version: number;
  description: string;
  statements: readonly string[];
}

/**
 * Append-only SQLite migrations. Never edit an applied migration; add the next
 * integer version so existing prototype databases remain upgradeable.
 */
export const SQLITE_MIGRATIONS: readonly SQLiteMigration[] = [
  {
    version: 1,
    description: "Create normalized operational monitoring event history",
    statements: [
      `CREATE TABLE IF NOT EXISTS monitoring_events (
        id TEXT PRIMARY KEY,
        source_event_id TEXT NOT NULL CHECK (length(trim(source_event_id)) > 0),
        source TEXT NOT NULL CHECK (source IN ('mock', 'jetson', 'unknown')),
        event_timestamp_utc TEXT NOT NULL,
        event_type TEXT NOT NULL,
        scenario_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        title TEXT NOT NULL,
        detail TEXT NOT NULL,
        system_status TEXT NOT NULL,
        device_connection_status TEXT NOT NULL,
        heart_rate_bpm INTEGER,
        imu_state TEXT NOT NULL,
        vision_state TEXT NOT NULL,
        fall_confidence REAL,
        fall_detected INTEGER NOT NULL CHECK (fall_detected IN (0, 1)),
        emergency_tier TEXT NOT NULL,
        voice_verification_status TEXT NOT NULL,
        alert_dispatch_status TEXT NOT NULL,
        normalized_payload_json TEXT,
        created_at_utc TEXT NOT NULL
      )`,
      `CREATE INDEX IF NOT EXISTS idx_monitoring_events_timestamp_utc
       ON monitoring_events(event_timestamp_utc DESC)`,
      `CREATE UNIQUE INDEX IF NOT EXISTS idx_monitoring_events_source_event
       ON monitoring_events(source, source_event_id)`
    ]
  }
];
