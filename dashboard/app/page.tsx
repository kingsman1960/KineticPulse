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

export default function HomePage() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    let mounted = true;
    const poll = async () => {
      try {
        const res = await fetch(`${httpBase}/sessions`, {
          headers: caregiverToken ? { Authorization: `Bearer ${caregiverToken}` } : {}
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (mounted) setSessions(Array.isArray(json.sessions) ? json.sessions : []);
      } catch (e: any) {
        if (mounted) setError(`Could not load sessions: ${e?.message ?? String(e)}`);
      }
    };
    poll();
    const timer = setInterval(poll, 3000);
    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, []);

  return (
    <main style={{ maxWidth: 1000, margin: "0 auto", padding: 24 }}>
      <h1 style={{ marginTop: 0 }}>KineticPulse Caregiver Dashboard</h1>
      <p style={{ opacity: 0.85 }}>
        Active emergency sessions published by Jetson. Click a session to open live stream.
      </p>
      {error ? <p style={{ color: "#fca5a5" }}>{error}</p> : null}

      <div style={{ display: "grid", gap: 12 }}>
        {sessions.length === 0 ? (
          <div style={{ padding: 16, border: "1px solid #334155", borderRadius: 8 }}>
            No active sessions.
          </div>
        ) : (
          sessions.map((s) => (
            <Link
              key={s.session_id}
              href={`/session/${encodeURIComponent(s.session_id)}`}
              style={{
                textDecoration: "none",
                color: "inherit",
                border: "1px solid #334155",
                borderRadius: 8,
                padding: 14,
                background: "#111827"
              }}
            >
              <div style={{ fontWeight: 700 }}>{s.session_id}</div>
              <div style={{ fontSize: 14, opacity: 0.8 }}>
                status={s.status} tier={s.meta?.tier ?? "n/a"} scenario={s.meta?.scenario ?? "n/a"}
              </div>
              <div style={{ fontSize: 13, opacity: 0.75 }}>
                subject={s.meta?.subject_id ?? "unknown"} location={s.meta?.location ?? "unknown"}
              </div>
            </Link>
          ))
        )}
      </div>
    </main>
  );
}
