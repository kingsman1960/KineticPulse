"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

type Props = { params: { id: string } };

const wsBase = process.env.NEXT_PUBLIC_SIGNALING_WS_BASE ?? "ws://localhost:8787/ws";
const caregiverToken = process.env.NEXT_PUBLIC_CAREGIVER_TOKEN ?? "";

export default function SessionPage({ params }: Props) {
  const sessionId = useMemo(() => decodeURIComponent(params.id), [params.id]);
  const [state, setState] = useState<string>("idle");
  const [error, setError] = useState<string>("");
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
      if (!alive) return;
    };
  }, [sessionId]);

  return (
    <main style={{ maxWidth: 1100, margin: "0 auto", padding: 24 }}>
      <div style={{ marginBottom: 14 }}>
        <Link href="/" style={{ color: "#93c5fd" }}>← Back to sessions</Link>
      </div>
      <h1 style={{ marginTop: 0 }}>Session {sessionId}</h1>
      <p style={{ opacity: 0.8 }}>Connection state: {state}</p>
      {error ? <p style={{ color: "#fca5a5" }}>{error}</p> : null}
      <video
        ref={videoRef}
        autoPlay
        playsInline
        controls
        muted={false}
        style={{ width: "100%", borderRadius: 10, background: "#020617", border: "1px solid #334155" }}
      />
    </main>
  );
}
