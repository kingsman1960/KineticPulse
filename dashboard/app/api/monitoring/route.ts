import { NextRequest } from "next/server";
import { createMonitoringDataSource } from "../../../lib/monitoring/dataSources";
import {
  EventStoreMonitoringRepository,
  type MonitoringRepository
} from "../../../lib/monitoring/eventStore";
import { handleMonitoringRequest } from "../../../lib/monitoring/monitoringApiHandler";
import { getMonitoringPersistenceConfig } from "../../../lib/monitoring/persistenceConfig";
import { SQLiteEventStore } from "../../../lib/monitoring/sqliteEventStore";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const globalStore = globalThis as typeof globalThis & {
  kineticPulseMonitoringRepository?: MonitoringRepository;
};

function getMonitoringRepository(): MonitoringRepository {
  if (globalStore.kineticPulseMonitoringRepository) {
    return globalStore.kineticPulseMonitoringRepository;
  }
  const config = getMonitoringPersistenceConfig();
  const eventStore = new SQLiteEventStore({
    dbPath: config.dbPath,
    recentLimit: config.eventLimit,
    retentionDays: config.retentionDays
  });
  const repository = new EventStoreMonitoringRepository(eventStore, config.eventLimit);
  globalStore.kineticPulseMonitoringRepository = repository;
  return repository;
}

export async function GET(request: NextRequest) {
  return handleMonitoringRequest(request, {
    createDataSource: createMonitoringDataSource,
    getRepository: getMonitoringRepository
  });
}
