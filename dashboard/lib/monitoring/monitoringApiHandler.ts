import { NextRequest, NextResponse } from "next/server";
import type { MonitoringDataSource } from "./dataSources";
import type { MonitoringRepository } from "./eventStore";

export interface MonitoringApiDependencies {
  createDataSource: () => MonitoringDataSource;
  getRepository: () => MonitoringRepository;
}

/** Injectable server handler kept outside the Next.js route module for testing. */
export async function handleMonitoringRequest(
  _request: NextRequest,
  dependencies: MonitoringApiDependencies
) {
  try {
    const source = dependencies.createDataSource();
    const model = await source.read();
    const repository = dependencies.getRepository();
    return NextResponse.json(repository.save(model, source.source), {
      headers: { "Cache-Control": "no-store" }
    });
  } catch (reason) {
    const message = reason instanceof Error ? reason.message : "Monitoring backend unavailable";
    return NextResponse.json({ error: message }, { status: 503 });
  }
}
