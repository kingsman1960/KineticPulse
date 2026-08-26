"use client";

import { useEffect, useState } from "react";
import MonitoringDashboard from "./components/MonitoringDashboard";
import { fetchMonitoringSnapshot } from "../lib/monitoring/clientDataSource";
import type { MonitoringModel } from "../lib/monitoring/model";

const POLL_INTERVAL_MS = 3000;

export default function HomePage() {
  const [model, setModel] = useState<MonitoringModel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    async function refresh() {
      try {
        const nextModel = await fetchMonitoringSnapshot(controller.signal);
        if (!active) return;
        setModel(nextModel);
        setError(null);
      } catch (reason) {
        if (!active || controller.signal.aborted) return;
        setError(reason instanceof Error ? reason.message : "Monitoring backend unavailable");
      } finally {
        if (active) setLoading(false);
      }
    }

    setLoading(true);
    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => {
      active = false;
      controller.abort();
      window.clearInterval(timer);
    };
  }, []);

  return (
    <MonitoringDashboard
      model={model}
      loading={loading}
      error={error}
    />
  );
}
