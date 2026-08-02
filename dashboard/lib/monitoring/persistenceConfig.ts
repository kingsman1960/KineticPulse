import path from "node:path";

export const DEFAULT_MONITORING_EVENT_LIMIT = 30;
export const DEFAULT_MONITORING_RETENTION_DAYS = 30;

export interface MonitoringPersistenceConfig {
  dbPath: string;
  eventLimit: number;
  retentionDays: number;
}

function positiveInteger(name: string, value: string | undefined, fallback: number): number {
  if (value === undefined || value.trim() === "") return fallback;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${name} must be a positive integer`);
  }
  return parsed;
}

/** Reads server-only persistence settings without exposing them to client code. */
export function getMonitoringPersistenceConfig(
  env: NodeJS.ProcessEnv = process.env,
  cwd = process.cwd()
): MonitoringPersistenceConfig {
  const configuredPath = env.MONITORING_DB_PATH?.trim();
  const dbPath = configuredPath
    ? path.resolve(cwd, configuredPath)
    : path.resolve(cwd, "runtime", "monitoring.db");

  return {
    dbPath,
    eventLimit: positiveInteger(
      "MONITORING_EVENT_LIMIT",
      env.MONITORING_EVENT_LIMIT,
      DEFAULT_MONITORING_EVENT_LIMIT
    ),
    retentionDays: positiveInteger(
      "MONITORING_RETENTION_DAYS",
      env.MONITORING_RETENTION_DAYS,
      DEFAULT_MONITORING_RETENTION_DAYS
    )
  };
}
