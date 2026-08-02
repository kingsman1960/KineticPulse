import type { MonitoringEvent, MonitoringModel } from "./model";

export type MonitoringEventSource = "mock" | "jetson" | "unknown";

export interface EventPersistenceContext {
  /** Distinguishes development mock records from Jetson/unknown records. */
  source: MonitoringEventSource;
  /** Normalized operational snapshot stored beside each emitted event. */
  model: MonitoringModel;
}

export interface EventStore {
  add(events: MonitoringEvent[], context: EventPersistenceContext): MonitoringEvent[];
  list(limit?: number): MonitoringEvent[];
  cleanupOlderThan(cutoffUtcIso: string): number;
  close?(): void;
}

/**
 * Bounded process-local fallback. It remains useful for unit tests and explicit
 * deployments that cannot open SQLite; data is lost on backend restart.
 */
export class InMemoryEventStore implements EventStore {
  private events = new Map<string, MonitoringEvent>();

  constructor(private readonly limit = 30) {}

  add(events: MonitoringEvent[], context: EventPersistenceContext): MonitoringEvent[] {
    for (const event of events) {
      this.events.set(`${context.source}:${event.id}`, event);
    }
    const boundedEntries = [...this.events.entries()]
      .sort(([, a], [, b]) => b.timestampMs - a.timestampMs || a.id.localeCompare(b.id))
      .slice(0, this.limit);
    const retainedKeys = new Set(boundedEntries.map(([key]) => key));
    for (const key of this.events.keys()) {
      if (!retainedKeys.has(key)) this.events.delete(key);
    }
    return boundedEntries.map(([, event]) => event);
  }

  list(limit = this.limit): MonitoringEvent[] {
    return [...this.events.values()]
      .sort((a, b) => b.timestampMs - a.timestampMs || a.id.localeCompare(b.id))
      .slice(0, limit);
  }

  cleanupOlderThan(cutoffUtcIso: string): number {
    const cutoffMs = Date.parse(cutoffUtcIso);
    if (!Number.isFinite(cutoffMs)) throw new Error("Retention cutoff must be a valid UTC ISO-8601 timestamp");
    let removed = 0;
    for (const [key, event] of this.events) {
      if (event.timestampMs < cutoffMs) {
        this.events.delete(key);
        removed += 1;
      }
    }
    return removed;
  }
}

export interface MonitoringRepository {
  save(model: MonitoringModel, source?: MonitoringEventSource): MonitoringModel;
  latest(): MonitoringModel | null;
}

/** Stores latest state in-process while delegating history to an EventStore. */
export class EventStoreMonitoringRepository implements MonitoringRepository {
  private current: MonitoringModel | null = null;

  constructor(
    private readonly eventStore: EventStore,
    private readonly recentLimit = 30
  ) {}

  save(model: MonitoringModel, source: MonitoringEventSource = "unknown"): MonitoringModel {
    this.current = {
      ...model,
      recentEvents: this.eventStore.add(model.recentEvents, { source, model }).slice(0, this.recentLimit)
    };
    return this.current;
  }

  latest(): MonitoringModel | null {
    return this.current ? { ...this.current, recentEvents: [...this.current.recentEvents] } : null;
  }

  close(): void {
    this.eventStore.close?.();
  }
}

/** Backward-compatible explicit in-memory repository for tests/fallback use. */
export class InMemoryMonitoringRepository extends EventStoreMonitoringRepository {
  constructor(eventStore: EventStore = new InMemoryEventStore(), recentLimit = 30) {
    super(eventStore, recentLimit);
  }
}
