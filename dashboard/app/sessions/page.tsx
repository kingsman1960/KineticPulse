"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

type SessionSummary = {
  session_id: string;
  status: string;
  created_at_ms: number;
  meta?: {
    tier?: string;
    scenario?: string;
    subject_id?: string;
    location?: string;
  };
};

const httpBase = process.env.NEXT_PUBLIC_SIGNALING_HTTP_BASE ?? "http://localhost:8787";
const caregiverToken = process.env.NEXT_PUBLIC_CAREGIVER_TOKEN ?? "";

/** Preserves the original caregiver session listing beside the monitoring MVP. */
export default function SessionsPage() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    const poll = async () => {
      try {
        const response = await fetch(`${httpBase}/sessions`, {
          headers: caregiverToken ? { Authorization: `Bearer ${caregiverToken}` } : {}
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const json = await response.json();
        if (mounted) {
          setSessions(Array.isArray(json.sessions) ? json.sessions : []);
          setError("");
        }
      } catch (reason) {
        if (mounted) setError(`Could not load sessions: ${reason instanceof Error ? reason.message : String(reason)}`);
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 3000);
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <main style={{ maxWidth: 1000, margin: "0 auto", padding: 24 }}>
      <Link href="/" style={{ color: "#202a36" }}>← Back to monitoring</Link>
      <h1>KineticPulse Caregiver Sessions</h1>
      <p>Active emergency sessions published by Jetson. Select a session to open its live stream.</p>
      {error ? <p style={{ color: "#b91c1c" }}>{error}</p> : null}
      <div style={{ display: "grid", gap: 12 }}>
        {sessions.length === 0 ? (
          <div style={{ padding: 16, border: "1px solid #d1d5db", borderRadius: 12, background: "white" }}>No active sessions.</div>
        ) : sessions.map((session) => (
          <Link
            key={session.session_id}
            href={`/session/${encodeURIComponent(session.session_id)}`}
            style={{ textDecoration: "none", color: "inherit", border: "1px solid #d1d5db", borderRadius: 12, padding: 14, background: "white" }}
          >
            <div style={{ fontWeight: 700 }}>{session.session_id}</div>
            <div style={{ fontSize: 14, color: "#4b5563" }}>status={session.status} tier={session.meta?.tier ?? "n/a"} scenario={session.meta?.scenario ?? "n/a"}</div>
            <div style={{ fontSize: 13, color: "#6b7280" }}>subject={session.meta?.subject_id ?? "unknown"} location={session.meta?.location ?? "unknown"}</div>
          </Link>
        ))}
      </div>
    </main>
  );
}
