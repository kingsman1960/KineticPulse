import { NextRequest } from "next/server";
import { createMonitoringDataSource } from "../../../lib/monitoring/dataSources";
import {
  EventStoreMonitoringRepository,
  InMemoryEventStore,
  type EventStore,
  type MonitoringRepository
} from "../../../lib/monitoring/eventStore";
import { handleMonitoringRequest } from "../../../lib/monitoring/monitoringApiHandler";
import { getMonitoringPersistenceConfig } from "../../../lib/monitoring/persistenceConfig";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const globalStore = globalThis as typeof globalThis & {
  kineticPulseMonitoringRepository?: MonitoringRepository;
};

async function createEventStore(config: ReturnType<typeof getMonitoringPersistenceConfig>): Promise<EventStore> {
  try {
    const { SQLiteEventStore } = await import("../../../lib/monitoring/sqliteEventStore");
    return new SQLiteEventStore({
      dbPath: config.dbPath,
      recentLimit: config.eventLimit,
      retentionDays: config.retentionDays
    });
  } catch (reason) {
    // ponytail: better-sqlite3 needs a native build; in-memory if gyp/bindings missing.
    console.warn("SQLite unavailable; using in-memory event store:", reason);
    return new InMemoryEventStore(config.eventLimit);
  }
}

async function getMonitoringRepository(): Promise<MonitoringRepository> {
  if (globalStore.kineticPulseMonitoringRepository) {
    return globalStore.kineticPulseMonitoringRepository;
  }
  const config = getMonitoringPersistenceConfig();
  const repository = new EventStoreMonitoringRepository(await createEventStore(config), config.eventLimit);
  globalStore.kineticPulseMonitoringRepository = repository;
  return repository;
}

export async function GET(request: NextRequest) {
  const repository = await getMonitoringRepository();
  return handleMonitoringRequest(request, {
    createDataSource: createMonitoringDataSource,
    getRepository: () => repository
  });
}
