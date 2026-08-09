"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

type Props = { params: { id: string } };

type SessionMeta = {
  tier?: string;
  scenario?: string;
  subject_id?: string;
  location?: string;
  reason?: string;
  detector_class?: string;
  action_class?: string;
  action_confidence?: number;
  heart_rate_bpm?: number | null;
  hr_signature?: string | null;
  accel_magnitude_g?: number | null;
  accel_signature?: string | null;
  extra?: { voice_verdict?: string };
};

const wsBase = process.env.NEXT_PUBLIC_SIGNALING_WS_BASE ?? "ws://localhost:8787/ws";
const caregiverToken = process.env.NEXT_PUBLIC_CAREGIVER_TOKEN ?? "";

function MetaRow({ label, value }: { label: string; value?: string | number | null }) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "6px 0", borderBottom: "1px solid #e5e7eb" }}>
      <span style={{ color: "#6b7280", fontSize: 13 }}>{label}</span>
      <span style={{ fontWeight: 600, fontSize: 13, textAlign: "right" }}>{String(value)}</span>
    </div>
  );
}

export default function SessionPage({ params }: Props) {
  const sessionId = useMemo(() => decodeURIComponent(params.id), [params.id]);
  const [state, setState] = useState<string>("idle");
  const [error, setError] = useState<string>("");
  const [meta, setMeta] = useState<SessionMeta | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    let alive = true;
    let pc: RTCPeerConnection | null = null;
    let ws: WebSocket | null = null;

    const run = async () => {
      try {
        setState("connecting");
        pc = new RTCPeerConnection({
          iceServers: [{ urls: ["stun:stun.l.google.com:19302"] }]
        });

        pc.ontrack = (ev) => {
          if (!videoRef.current) return;
          const [stream] = ev.streams;
          if (stream) videoRef.current.srcObject = stream;
        };
        pc.onconnectionstatechange = () => {
          if (pc) setState(pc.connectionState);
        };
        pc.onicecandidate = (ev) => {
          if (!ws || ws.readyState !== WebSocket.OPEN || !ev.candidate) return;
          ws.send(JSON.stringify({
            type: "ice-candidate",
            payload: {
              session_id: sessionId,
              role: "caregiver",
              candidate: ev.candidate.candidate,
              sdpMid: ev.candidate.sdpMid,
              sdpMLineIndex: ev.candidate.sdpMLineIndex
            }
          }));
        };

        const auth = caregiverToken ? `?token=${encodeURIComponent(caregiverToken)}` : "";
        ws = new WebSocket(`${wsBase}${auth}`);
        ws.onopen = () => {
          ws?.send(JSON.stringify({
            type: "join-session",
            payload: { session_id: sessionId }
          }));
        };
        ws.onmessage = async (event) => {
          const msg = JSON.parse(event.data);
          const type = msg?.type;
          const payload = msg?.payload ?? {};
          if (type === "offer") {
            if (payload.meta && alive) setMeta(payload.meta as SessionMeta);
            await pc!.setRemoteDescription(new RTCSessionDescription(payload.offer));
            const answer = await pc!.createAnswer();
            await pc!.setLocalDescription(answer);
            ws?.send(JSON.stringify({
              type: "answer",
              payload: {
                session_id: sessionId,
                answer: {
                  type: pc!.localDescription!.type,
                  sdp: pc!.localDescription!.sdp
                }
              }
            }));
          } else if (type === "ice-candidate" && payload.candidate) {
            await pc!.addIceCandidate({
              candidate: payload.candidate,
              sdpMid: payload.sdpMid ?? null,
              sdpMLineIndex: payload.sdpMLineIndex ?? null
            });
          } else if (type === "session-closed") {
            setState("closed");
          }
        };
        ws.onerror = () => setError("WebSocket error");
      } catch (e: any) {
        setError(e?.message ?? String(e));
      }
    };

    run();
    return () => {
      alive = false;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "close-session", payload: { session_id: sessionId } }));
      }
      ws?.close();
      pc?.close();
    };
  }, [sessionId]);

  const bpm = meta?.heart_rate_bpm;
  const g = meta?.accel_magnitude_g;

  return (
    <main style={{ maxWidth: 1100, margin: "0 auto", padding: 24 }}>
      <div style={{ marginBottom: 14 }}>
        <Link href="/sessions" style={{ color: "#202a36" }}>← Back to sessions</Link>
      </div>
      <h1 style={{ marginTop: 0 }}>Session {sessionId}</h1>
      <p style={{ opacity: 0.8 }}>Connection state: {state}</p>
      {error ? <p style={{ color: "#b91c1c" }}>{error}</p> : null}

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 280px", gap: 16, alignItems: "start" }}>
        <video
          ref={videoRef}
          autoPlay
          playsInline
          controls
          muted={false}
          style={{ width: "100%", borderRadius: 10, background: "#020617", border: "1px solid #d1d5db" }}
        />
        <aside style={{ border: "1px solid #d1d5db", borderRadius: 12, padding: 14, background: "white" }}>
          <div style={{ fontWeight: 700, marginBottom: 8 }}>Alert context</div>
          <MetaRow label="Tier" value={meta?.tier} />
          <MetaRow label="Scenario" value={meta?.scenario} />
          <MetaRow label="Subject" value={meta?.subject_id} />
          <MetaRow label="Location" value={meta?.location} />
          <MetaRow label="Reason" value={meta?.reason} />
          <MetaRow label="Heart rate" value={bpm == null ? null : `${bpm} BPM`} />
          <MetaRow label="HR signature" value={meta?.hr_signature} />
          <MetaRow label="Accel" value={g == null ? null : `${g.toFixed(2)} g`} />
          <MetaRow label="Accel signature" value={meta?.accel_signature} />
          <MetaRow label="Detector" value={meta?.detector_class} />
          <MetaRow label="Action" value={meta?.action_class} />
          <MetaRow
            label="Action conf"
            value={meta?.action_confidence == null ? null : meta.action_confidence.toFixed(2)}
          />
          <MetaRow label="Voice" value={meta?.extra?.voice_verdict} />
          {!meta ? <p style={{ fontSize: 13, color: "#6b7280" }}>Waiting for session offer…</p> : null}
        </aside>
      </div>
    </main>
  );
}
