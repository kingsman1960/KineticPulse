"use client";

import { Menu, WifiOff, X } from "lucide-react";
import Link from "next/link";
import React, { useEffect, useState } from "react";
import type { MonitoringModel } from "../../lib/monitoring/model";
import { appendVitalSample, type VitalSample } from "../../lib/monitoring/sparkline";
import MonitoringOverview from "./MonitoringOverview";

type Props = {
  model: MonitoringModel | null;
  loading: boolean;
  error: string | null;
};

function words(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter: string) => letter.toUpperCase());
}

function percent(value: number | null): string {
  return value === null ? "No result" : `${Math.round(value * 100)}%`;
}

function emergencyLabel(level: MonitoringModel["emergency"]["level"]): string {
  const labels = {
    none: "None",
    tier_0_dismiss: "Tier 0 — Dismissed",
    tier_1_verify: "Tier 1 — Verify",
    tier_2_seizure: "Tier 2 — Seizure",
    tier_2_cardiac: "Tier 2 — Cardiac"
  };
  return labels[level];
}

function stateTone(model: MonitoringModel): "normal" | "warning" | "critical" {
  if (
    model.emergency.level === "tier_2_cardiac" ||
    model.emergency.level === "tier_2_seizure" ||
    model.voiceVerification.status === "distress" ||
    (model.fall.detected && model.alertDispatch.status === "sent")
  ) return "critical";
  if (model.emergency.level === "tier_1_verify") return "warning";
  if (model.system.connection !== "connected" || model.sensor.connection !== "connected") return "warning";
  if (model.fall.detected) return "critical";
  return "normal";
}

export default function MonitoringDashboard({
  model,
  loading,
  error
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [vitals, setVitals] = useState<VitalSample[]>([]);
  const tone = model ? stateTone(model) : "warning";

  useEffect(() => {
    if (!model) return;
    setVitals((prev) => appendVitalSample(prev, { t: model.updatedAtMs, bpm: model.heartRate.bpm }));
  }, [model]);

  return (
    <div className="monitoring-page">
      <header className="topbar">
        <a className="brand" href="#overview" aria-label="KineticPulse monitoring home">KineticPulse</a>
        <nav className="desktop-nav" aria-label="Primary navigation">
          <a href="#overview">Overview</a>
          <a href="#vitals">Vitals</a>
          <a href="#detection">Detection</a>
          <a href="#events">Events</a>
          <Link href="/sessions">Live sessions</Link>
        </nav>
        <button
          className="mobile-menu-button"
          type="button"
          aria-label={menuOpen ? "Close navigation" : "Open navigation"}
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((open) => !open)}
        >
          {menuOpen ? <X /> : <Menu />}
        </button>
        <nav className={`mobile-nav${menuOpen ? " open" : ""}`} aria-label="Mobile navigation">
          <a href="#overview" onClick={() => setMenuOpen(false)}>Overview</a>
          <a href="#vitals" onClick={() => setMenuOpen(false)}>Vitals</a>
          <a href="#detection" onClick={() => setMenuOpen(false)}>Detection</a>
          <a href="#events" onClick={() => setMenuOpen(false)}>Events</a>
          <Link href="/sessions" onClick={() => setMenuOpen(false)}>Live sessions</Link>
        </nav>
      </header>

      <main className="dashboard-shell" id="overview">
        <section className="dashboard-intro">
          <div>
            <p className="eyebrow">Edge-AI safety monitoring</p>
            <h1>Always aware.<span>Ready to respond.</span></h1>
            <p className="intro-copy">
              Live sensor, vision, and emergency signals for {model?.subjectId ?? "the monitored subject"}.
            </p>
          </div>
          <div className="live-pill" aria-live="polite">
            <span className={`live-dot ${tone === "normal" ? "" : tone}`} />
            {model ? `${model.system.label} · ${model.location}` : loading ? "Connecting…" : "Unavailable"}
          </div>
        </section>

        {loading && !model ? (
          <section className="glass-card state-card" aria-label="Loading monitoring data">
            <div><div className="spinner" aria-hidden="true" /><h2>Connecting to monitoring</h2><p>Preparing the latest edge and sensor state.</p></div>
          </section>
        ) : error && !model ? (
          <section className="glass-card state-card" role="alert">
            <div><WifiOff /><h2>Backend unavailable</h2><p>{error}. The dashboard will retry automatically.</p></div>
          </section>
        ) : model ? (
          <>
            {error ? <div className="live-pill" role="status"><span className="live-dot warning" />Latest state shown; reconnecting to backend.</div> : null}
            <MonitoringOverview
              model={model}
              tone={tone}
              heartStatusLabel={words(model.heartRate.status)}
              fallConfidenceLabel={percent(model.fall.confidence)}
              emergencyLevelLabel={emergencyLabel(model.emergency.level)}
              vitals={vitals}
            />
          </>
        ) : null}
      </main>
    </div>
  );
}
