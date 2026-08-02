import { NextRequest, NextResponse } from "next/server";
import type { MonitoringDataSource } from "./dataSources";
import type { MonitoringRepository } from "./eventStore";
import {
  DEFAULT_MONITORING_SCENARIO,
  MONITORING_SCENARIOS,
  type MonitoringScenario
} from "./model";

export interface MonitoringApiDependencies {
  createDataSource: () => MonitoringDataSource;
  getRepository: () => MonitoringRepository;
}

function parseScenario(value: string | null): MonitoringScenario {
  if (value && MONITORING_SCENARIOS.includes(value as MonitoringScenario)) {
    return value as MonitoringScenario;
  }
  return DEFAULT_MONITORING_SCENARIO;
}

/** Injectable server handler kept outside the Next.js route module for testing. */
export async function handleMonitoringRequest(
  request: NextRequest,
  dependencies: MonitoringApiDependencies
) {
  try {
    const source = dependencies.createDataSource();
    const scenario = parseScenario(request.nextUrl.searchParams.get("scenario"));
    const model = await source.read(scenario);
    const repository = dependencies.getRepository();
    return NextResponse.json(repository.save(model, source.source), {
      headers: { "Cache-Control": "no-store" }
    });
  } catch (reason) {
    const message = reason instanceof Error ? reason.message : "Monitoring backend unavailable";
    return NextResponse.json({ error: message }, { status: 503 });
  }
}
