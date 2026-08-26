"use client";

import {
  Activity,
  BellRing,
  BrainCircuit,
  Camera,
  Check,
  ChevronRight,
  CircleAlert,
  Clock3,
  Eye,
  HeartPulse,
  MapPin,
  Mic2,
  Radio,
  Server,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  Wifi,
  WifiOff,
  Zap
} from "lucide-react";
import React, { useMemo, useState, type CSSProperties, type ReactNode } from "react";
import {
  type MonitoringEvent,
  type MonitoringModel,
  type MonitoringSeverity
} from "../../lib/monitoring/model";

type Tone = "normal" | "warning" | "critical";
type EventFilter = "all" | MonitoringSeverity;

type Props = {
  model: MonitoringModel;
  tone: Tone;
  heartStatusLabel: string;
  fallConfidenceLabel: string;
  emergencyLevelLabel: string;
};

const EVENT_SECTIONS: Array<{
  severity: MonitoringSeverity;
  label: string;
  description: string;
}> = [
  { severity: "critical", label: "Urgent", description: "Immediate-response activity" },
  { severity: "warning", label: "Attention", description: "Signals requiring review" },
  { severity: "info", label: "System activity", description: "Routine monitoring updates" }
];

function words(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function percent(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

function time(timestampMs: number): string {
  return new Intl.DateTimeFormat("en", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  }).format(timestampMs);
}

function relativeTime(timestampMs: number, updatedAtMs: number): string {
  const elapsedSeconds = Math.max(0, Math.round((updatedAtMs - timestampMs) / 1000));
  if (elapsedSeconds < 10) return "Now";
  if (elapsedSeconds < 60) return `${elapsedSeconds}s ago`;
  const minutes = Math.round(elapsedSeconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric" }).format(timestampMs);
}

function statusHeadline(model: MonitoringModel, tone: Tone): string {
  if (tone === "critical") return "Emergency response active";
  if (model.sensor.connection === "disconnected") return "Monitoring has limited coverage";
  if (tone === "warning") return "Verification is in progress";
  return "All monitoring signals are steady";
}

function pipelineState(
  value: string,
  kind: "fusion" | "voice" | "dispatch"
): Tone | "muted" {
  if (kind === "fusion") {
    if (value.startsWith("tier_2")) return "critical";
    if (value === "tier_1_verify") return "warning";
    return "normal";
  }
  if (kind === "voice") {
    if (value === "distress") return "critical";
    if (value === "pending" || value === "unknown") return "warning";
    if (value === "not_required") return "muted";
    return "normal";
  }
  if (value === "failed") return "critical";
  if (value === "pending") return "warning";
  if (value === "idle") return "muted";
  return "normal";
}

function eventIcon(category: MonitoringEvent["category"]): ReactNode {
  const icons = {
    system: <Server />,
    sensor: <Zap />,
    vision: <Camera />,
    fusion: <BrainCircuit />,
    voice: <Mic2 />,
    alert: <BellRing />
  };
  return icons[category];
}

export default function MonitoringOverview({
  model,
  tone,
  heartStatusLabel,
  fallConfidenceLabel,
  emergencyLevelLabel
}: Props) {
  const [eventFilter, setEventFilter] = useState<EventFilter>("all");
  const counts = useMemo(
    () => ({
      all: model.recentEvents.length,
      critical: model.recentEvents.filter((event) => event.severity === "critical").length,
      warning: model.recentEvents.filter((event) => event.severity === "warning").length,
      info: model.recentEvents.filter((event) => event.severity === "info").length
    }),
    [model.recentEvents]
  );

  const visibleSections = useMemo(
    () =>
      EVENT_SECTIONS.map((section) => ({
        ...section,
        events: model.recentEvents.filter(
          (event) =>
            event.severity === section.severity &&
            (eventFilter === "all" || event.severity === eventFilter)
        )
      })).filter((section) => section.events.length > 0),
    [eventFilter, model.recentEvents]
  );

  return (
    <>
      <section className="system-ribbon glass-card" aria-label="Monitoring connections">
        <StatusItem
          icon={model.system.connection === "connected" ? <Wifi /> : <WifiOff />}
          label="System"
          value={model.system.label}
          state={model.system.connection}
        />
        <StatusItem
          icon={<Radio />}
          label="Sensor"
          value={model.sensor.label}
          state={model.sensor.connection}
        />
        <StatusItem icon={<MapPin />} label="Location" value={model.location} state="connected" />
        <StatusItem
          icon={<Clock3 />}
          label="Last sync"
          value={time(model.updatedAtMs)}
          state="connected"
        />
      </section>

      <section className={`command-banner glass-card ${tone}`} aria-label="Current safety assessment">
        <div className="command-icon" aria-hidden="true">
          {tone === "normal" ? <ShieldCheck /> : tone === "critical" ? <TriangleAlert /> : <CircleAlert />}
        </div>
        <div className="command-copy">
          <p className="section-kicker">Current assessment</p>
          <h2>{statusHeadline(model, tone)}</h2>
          <p>{model.emergency.reason}</p>
        </div>
        <div className="command-badges">
          <StatusBadge label="Emergency" value={emergencyLevelLabel} tone={tone} />
          <StatusBadge
            label="Fall"
            value={model.fall.detected ? "Detected" : "Clear"}
            tone={model.fall.detected ? "critical" : "normal"}
          />
        </div>
      </section>

      <div className="visual-dashboard">
        <div className="visual-canvas">
          <section className="glass-card signal-overview" id="vitals" aria-label="Signal overview">
            <SectionHeader
              kicker="Live signal"
              title="Vital & fall overview"
              meta={model.heartRate.status === "unavailable" ? "Sensor unavailable" : "Current sample"}
            />
            <div className="signal-layout">
              <div
                className={`heart-visual ${model.heartRate.status === "pulse_lost" ? "critical" : model.heartRate.status === "unavailable" ? "muted" : ""}`}
              >
                <div className="heart-heading">
                  <span className="signal-icon"><HeartPulse /></span>
                  <div><span>Heart rate</span><strong>{heartStatusLabel}</strong></div>
                </div>
                <div className="heart-reading">
                  {model.heartRate.bpm === null ? (
                    <strong className="heart-unavailable">
                      {model.heartRate.status === "pulse_lost" ? "Pulse lost" : "No signal"}
                    </strong>
                  ) : (
                    <><strong>{model.heartRate.bpm}</strong><span>BPM</span></>
                  )}
                </div>
                <HeartRateScale bpm={model.heartRate.bpm} />
              </div>

              <div className="risk-visual">
                <RadialGauge
                  value={model.fall.confidence}
                  tone={tone}
                  label="Fall confidence"
                  displayValue={fallConfidenceLabel}
                />
                <div className="risk-copy">
                  <span className={`risk-status ${tone}`}>
                    {model.fall.detected ? <TriangleAlert /> : <Check />}
                    {model.fall.detected ? "Fall detected" : "No active fall"}
                  </span>
                  <p>Fusion confidence from the latest motion and vision result.</p>
                </div>
              </div>
            </div>
          </section>

          <section className="glass-card fusion-panel" id="detection" aria-label="Sensor fusion diagram">
            <SectionHeader
              kicker="Detection"
              title="Sensor fusion"
              meta={`Scenario ${model.emergency.scenario}`}
            />
            <div className="fusion-diagram">
              <div className="fusion-inputs">
                <SignalNode
                  icon={<Activity />}
                  source="ESP32 · IMU"
                  value={words(model.motion.state)}
                  detail={model.motion.magnitudeG === null ? "No IMU sample" : `${model.motion.magnitudeG.toFixed(2)} g`}
                  state={model.motion.state === "unknown" ? "muted" : model.motion.state === "impact" || model.motion.state === "tremor" ? "critical" : "normal"}
                />
                <SignalNode
                  icon={<Eye />}
                  source="Vision"
                  value={model.vision.state === "no_result" ? "No result" : words(model.vision.state)}
                  detail={model.vision.confidence === null ? "Camera unavailable" : `${percent(model.vision.confidence)} confidence`}
                  state={model.vision.state === "no_result" ? "muted" : model.vision.state === "fallen" || model.vision.state === "falling" ? "critical" : "normal"}
                />
              </div>
              <div className="fusion-connector" aria-hidden="true"><ChevronRight /></div>
              <div className={`fusion-core ${tone}`}>
                <span><BrainCircuit /></span>
                <small>Edge fusion</small>
                <strong>{emergencyLevelLabel}</strong>
              </div>
              <div className="fusion-connector" aria-hidden="true"><ChevronRight /></div>
              <div className={`fusion-output ${tone}`}>
                <span className="output-label">Decision</span>
                <strong>{model.fall.detected ? "Respond" : tone === "warning" ? "Verify" : "Monitor"}</strong>
                <p>{model.vision.actionClass ? `Action: ${words(model.vision.actionClass)}` : "No temporal result"}</p>
              </div>
            </div>
          </section>

          <section className="glass-card response-panel" aria-label="Emergency response flow">
            <SectionHeader kicker="Automation" title="Response flow" meta="Latest state" />
            <div className="response-track">
              <PipelineStep
                number="01"
                label="Fusion"
                value={emergencyLevelLabel}
                state={pipelineState(model.emergency.level, "fusion")}
                icon={<Sparkles />}
              />
              <span className="pipeline-line" aria-hidden="true" />
              <PipelineStep
                number="02"
                label="Voice check"
                value={words(model.voiceVerification.status)}
                state={pipelineState(model.voiceVerification.status, "voice")}
                icon={<Mic2 />}
              />
              <span className="pipeline-line" aria-hidden="true" />
              <PipelineStep
                number="03"
                label="Alert dispatch"
                value={words(model.alertDispatch.status)}
                state={pipelineState(model.alertDispatch.status, "dispatch")}
                icon={<BellRing />}
              />
            </div>
          </section>
        </div>

        <aside className="intelligence-rail" id="events">
          <section className="glass-card event-panel redesigned">
            <div className="event-panel-heading">
              <div>
                <p className="section-kicker">Activity timeline</p>
                <h2>Recent events</h2>
              </div>
              <span className="event-total">{counts.all}</span>
            </div>

            <div className="event-filters" aria-label="Filter recent events">
              {(["all", "critical", "warning", "info"] as EventFilter[]).map((filter) => (
                <button
                  type="button"
                  key={filter}
                  className={eventFilter === filter ? "active" : ""}
                  aria-pressed={eventFilter === filter}
                  onClick={() => setEventFilter(filter)}
                >
                  <span>{filter === "all" ? "All" : filter === "critical" ? "Urgent" : words(filter)}</span>
                  <strong>{counts[filter]}</strong>
                </button>
              ))}
            </div>

            <div className="organized-events">
              {visibleSections.length ? visibleSections.map((section) => (
                <section className="event-group" key={section.severity} aria-label={section.label}>
                  <div className="event-group-heading">
                    <div><span className={`severity-dot ${section.severity}`} /><h3>{section.label}</h3></div>
                    <span>{section.events.length}</span>
                  </div>
                  <p className="event-group-description">{section.description}</p>
                  <div className="event-timeline">
                    {section.events.map((event) => (
                      <article className={`timeline-event ${event.severity}`} key={event.id}>
                        <div className="timeline-marker" aria-hidden="true">{eventIcon(event.category)}</div>
                        <div className="timeline-content">
                          <div className="timeline-meta">
                            <span>{words(event.category)}</span>
                            <time dateTime={new Date(event.timestampMs).toISOString()} title={time(event.timestampMs)}>
                              {relativeTime(event.timestampMs, model.updatedAtMs)}
                            </time>
                          </div>
                          <h4>{event.title}</h4>
                          <p>{event.detail}</p>
                        </div>
                      </article>
                    ))}
                  </div>
                </section>
              )) : (
                <div className="empty-events"><Check /><p>No events in this category.</p></div>
              )}
            </div>
          </section>

        </aside>
      </div>
    </>
  );
}

function StatusItem({
  icon,
  label,
  value,
  state
}: {
  icon: ReactNode;
  label: string;
  value: string;
  state: MonitoringModel["system"]["connection"];
}) {
  return (
    <div className={`status-item ${state}`}>
      <span className="status-item-icon">{icon}</span>
      <div><small>{label}</small><strong>{value}</strong></div>
    </div>
  );
}

function StatusBadge({ label, value, tone }: { label: string; value: string; tone: Tone }) {
  return (
    <div className={`status-badge ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function SectionHeader({ kicker, title, meta }: { kicker: string; title: string; meta: string }) {
  return (
    <div className="visual-section-header">
      <div><p className="section-kicker">{kicker}</p><h2>{title}</h2></div>
      <span>{meta}</span>
    </div>
  );
}

function HeartRateScale({ bpm }: { bpm: number | null }) {
  const marker = bpm === null ? 0 : Math.min(100, Math.max(0, ((bpm - 40) / 120) * 100));
  const style = { "--heart-position": `${marker}%` } as CSSProperties;
  return (
    <div className={`heart-scale ${bpm === null ? "unavailable" : ""}`} style={style} aria-label={bpm === null ? "No heart-rate sample" : `Heart-rate scale showing ${bpm} BPM`}>
      <div className="heart-scale-track"><span /></div>
      <div className="heart-scale-labels"><span>40</span><span>100</span><span>160+</span></div>
    </div>
  );
}

function RadialGauge({ value, tone, label, displayValue }: { value: number | null; tone: Tone; label: string; displayValue: string }) {
  const degrees = value === null ? 0 : Math.min(1, Math.max(0, value)) * 360;
  const style = { "--gauge-progress": `${degrees}deg` } as CSSProperties;
  return (
    <div className={`radial-gauge ${tone} ${value === null ? "unavailable" : ""}`} style={style} role="img" aria-label={`${label}: ${percent(value)}`}>
      <div><strong>{displayValue}</strong><span>{label}</span></div>
    </div>
  );
}

function SignalNode({
  icon,
  source,
  value,
  detail,
  state
}: {
  icon: ReactNode;
  source: string;
  value: string;
  detail: string;
  state: Tone | "muted";
}) {
  return (
    <div className={`signal-node ${state}`}>
      <span className="node-icon">{icon}</span>
      <div><small>{source}</small><strong>{value}</strong><p>{detail}</p></div>
    </div>
  );
}

function PipelineStep({
  number,
  label,
  value,
  state,
  icon
}: {
  number: string;
  label: string;
  value: string;
  state: Tone | "muted";
  icon: ReactNode;
}) {
  return (
    <div className={`pipeline-step ${state}`}>
      <div className="pipeline-index"><span>{number}</span>{icon}</div>
      <small>{label}</small>
      <strong>{value}</strong>
    </div>
  );
}
