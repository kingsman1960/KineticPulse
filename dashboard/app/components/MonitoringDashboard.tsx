"use client";

import {
  Activity,
  BellRing,
  BrainCircuit,
  Camera,
  Gauge,
  HeartPulse,
  Menu,
  Mic2,
  Server,
  ShieldCheck,
  TriangleAlert,
  WifiOff,
  X,
  Zap
} from "lucide-react";
import Link from "next/link";
import React, { useState } from "react";
import type { MonitoringModel } from "../../lib/monitoring/model";
import MonitoringOverview from "./MonitoringOverview";

// Royalty-free Pexels footage representing the monitored living-room camera view.
const CAMERA_VIDEO_URL =
  "https://videos.pexels.com/video-files/7530572/7530572-hd_1280_720_25fps.mp4";

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

function time(timestampMs: number): string {
  return new Intl.DateTimeFormat("en", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(timestampMs);
}

export default function MonitoringDashboard({
  model,
  loading,
  error
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const tone = model ? stateTone(model) : "warning";

  return (
    <div className="monitoring-page">
      <section className="monitoring-hero">
        <video className="hero-video" autoPlay muted loop playsInline aria-hidden="true">
          <source src={CAMERA_VIDEO_URL} type="video/mp4" />
        </video>
        <div className="hero-wash" />
        <div className="hero-content">
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
                />
                {false ? ((model: MonitoringModel) => (
                <div className="dashboard-grid">
                  <section className="metrics-grid" id="vitals" aria-label="Current monitoring metrics">
                    <MetricCard icon={<Server />} label="System" value={model.system.label} note={`Last update ${time(model.updatedAtMs)}`} className={model.system.connection === "connected" ? "" : "disconnected"} />
                    <MetricCard icon={<Zap />} label="Sensor link" value={model.sensor.label} note="ESP32 telemetry transport" className={model.sensor.connection === "connected" ? "" : "disconnected"} />
                    <MetricCard icon={<HeartPulse />} label="Heart rate" value={model.heartRate.bpm === null ? model.heartRate.status === "pulse_lost" ? "Pulse lost" : "Unavailable" : `${model.heartRate.bpm}`} unit={model.heartRate.bpm === null ? undefined : "BPM"} note={words(model.heartRate.status)} className={model.heartRate.status === "pulse_lost" ? "danger" : model.heartRate.status === "unavailable" ? "disconnected" : ""} />
                    <MetricCard icon={<Activity />} label="Motion / IMU" value={words(model.motion.state)} note={model.motion.magnitudeG === null ? "No IMU sample" : `${model.motion.magnitudeG!.toFixed(2)} g magnitude`} className={model.motion.state === "impact" || model.motion.state === "tremor" ? "danger" : model.motion.state === "unknown" ? "disconnected" : ""} />
                    <MetricCard icon={<Camera />} label="Vision" value={model.vision.state === "no_result" ? "No camera result" : words(model.vision.state)} note={model.vision.confidence === null ? "Detection unavailable" : `${percent(model.vision.confidence)} detection confidence`} className={model.vision.state === "fallen" || model.vision.state === "falling" ? "danger" : model.vision.state === "no_result" ? "disconnected" : ""} />
                    <MetricCard icon={<Gauge />} label="Fall confidence" value={percent(model.fall.confidence)} note={model.fall.detected ? "Fall detected" : "No active fall"} confidence={model.fall.confidence} className={model.fall.detected ? "danger" : ""} />
                    <MetricCard icon={<TriangleAlert />} label="Fall status" value={model.fall.detected ? "Detected" : "Clear"} note={model.emergency.reason} className={model.fall.detected ? "danger" : ""} />
                    <MetricCard icon={<ShieldCheck />} label="Emergency level" value={emergencyLabel(model.emergency.level)} note={`Scenario ${model.emergency.scenario}`} className={model.emergency.level.startsWith("tier_2") || model.emergency.level === "tier_1_verify" ? "danger" : ""} />
                    <MetricCard icon={<Mic2 />} label="Voice verification" value={words(model.voiceVerification.status)} note={model.voiceVerification.status === "not_required" ? "No verification required" : "Voice worker state"} className={model.voiceVerification.status === "distress" ? "danger" : ""} />
                    <MetricCard icon={<BellRing />} label="Alert dispatch" value={words(model.alertDispatch.status)} note="Caregiver webhook status" className={model.alertDispatch.status === "failed" ? "danger" : ""} />
                    <MetricCard icon={<BrainCircuit />} label="Vision action" value={model.vision.actionClass ? words(model.vision.actionClass!) : "No result"} note="Temporal pipeline output" className={!model.vision.actionClass ? "disconnected" : ""} />
                  </section>

                  <aside id="events">
                    <section className="glass-card event-panel">
                      <div className="panel-header"><h2>Recent events</h2><span className="panel-meta">In-memory · latest {model.recentEvents.length}</span></div>
                      <div className="event-list">
                        {model.recentEvents.length ? model.recentEvents.map((event) => (
                          <article className={`event-item ${event.severity}`} key={event.id}>
                            <div className="event-title"><span>{event.title}</span><time className="event-time">{time(event.timestampMs)}</time></div>
                            <p className="event-detail">{event.detail}</p>
                          </article>
                        )) : <p className="event-detail">No recent events.</p>}
                      </div>
                    </section>

                  </aside>
                </div>
                ))(model!) : null}
              </>
            ) : null}
          </main>
        </div>
      </section>
    </div>
  );
}

function MetricCard({
  icon,
  label,
  value,
  unit,
  note,
  confidence,
  className = ""
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  unit?: string;
  note: string;
  confidence?: number | null;
  className?: string;
}) {
  return (
    <article className={`glass-card metric-card ${className}`} id={label === "Vision" ? "detection" : undefined}>
      <div className="metric-heading"><span>{label}</span>{icon}</div>
      <div>
        <div className="metric-value">{value}{unit ? <small>{unit}</small> : null}</div>
        {confidence !== undefined && confidence !== null ? <div className="confidence-track" aria-label={`${label} ${percent(confidence)}`}><div className="confidence-fill" style={{ width: percent(confidence) }} /></div> : null}
        <p className="metric-note">{note}</p>
      </div>
    </article>
  );
}
