import { useEffect, useRef, useState } from "react";
import {
  MediaStream,
  RTCIceCandidate,
  RTCPeerConnection,
  RTCSessionDescription
} from "react-native-webrtc";

import { AppSettings, SessionMeta } from "@/types/session";
import { buildWsUrl, parseIceServers } from "@/api/sessions";

export type PeerState = "idle" | "connecting" | "connected" | "failed" | "closed";

type TrackEvent = { streams: MediaStream[] };
type IceEvent = { candidate: RTCIceCandidate | null };

type PeerConnection = RTCPeerConnection & {
  onconnectionstatechange: (() => void) | null;
  ontrack: ((event: TrackEvent) => void) | null;
  onicecandidate: ((event: IceEvent) => void) | null;
};

type UseCaregiverPeerArgs = {
  sessionId: string;
  settings: AppSettings | null;
  enabled: boolean;
};

export function useCaregiverPeer({ sessionId, settings, enabled }: UseCaregiverPeerArgs) {
  const [connectionState, setConnectionState] = useState<PeerState>("idle");
  const [remoteStream, setRemoteStream] = useState<MediaStream | null>(null);
  const [sessionMeta, setSessionMeta] = useState<SessionMeta | null>(null);
  const [error, setError] = useState<string>("");
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!enabled || !settings || !sessionId) {
      return;
    }

    let alive = true;
    const pc = new RTCPeerConnection({
      iceServers: parseIceServers(settings.iceServersText)
    }) as PeerConnection;
    pcRef.current = pc;

    const wsUrl = buildWsUrl(settings);
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    const cleanup = () => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(
          JSON.stringify({
            type: "close-session",
            payload: { session_id: sessionId }
          })
        );
      }
      ws.close();
      pc.close();
      pcRef.current = null;
      wsRef.current = null;
    };

    const run = async () => {
      try {
        if (!alive) return;
        setConnectionState("connecting");
        setError("");

        pc.onconnectionstatechange = () => {
          const state = pc.connectionState as PeerState;
          if (state === "connected") {
            setConnectionState("connected");
          } else if (state === "failed") {
            setConnectionState("failed");
          } else if (state === "closed") {
            setConnectionState("closed");
          }
        };

        pc.ontrack = (event) => {
          const [stream] = event.streams;
          if (stream) {
            setRemoteStream(stream);
          }
        };

        pc.onicecandidate = (event) => {
          if (!event.candidate || ws.readyState !== WebSocket.OPEN) {
            return;
          }
          ws.send(
            JSON.stringify({
              type: "ice-candidate",
              payload: {
                session_id: sessionId,
                role: "caregiver",
                candidate: event.candidate.candidate,
                sdpMid: event.candidate.sdpMid,
                sdpMLineIndex: event.candidate.sdpMLineIndex
              }
            })
          );
        };

        ws.onopen = () => {
          ws.send(
            JSON.stringify({
              type: "join-session",
              payload: { session_id: sessionId }
            })
          );
        };

        ws.onmessage = async (event) => {
          let msg: { type?: string; payload?: Record<string, unknown> };
          try {
            msg = JSON.parse(String(event.data));
          } catch {
            return;
          }
          const type = msg.type;
          const payload = msg.payload ?? {};

          if (type === "offer") {
            const offer = payload.offer as { sdp: string; type: string };
            const meta = payload.meta as SessionMeta | undefined;
            if (meta) {
              setSessionMeta(meta);
            }
            await pc.setRemoteDescription(new RTCSessionDescription(offer));
            const answer = await pc.createAnswer();
            await pc.setLocalDescription(answer);
            ws.send(
              JSON.stringify({
                type: "answer",
                payload: {
                  session_id: sessionId,
                  answer: {
                    type: pc.localDescription?.type,
                    sdp: pc.localDescription?.sdp
                  }
                }
              })
            );
          } else if (type === "ice-candidate" && payload.candidate) {
            await pc.addIceCandidate(
              new RTCIceCandidate({
                candidate: String(payload.candidate),
                sdpMid: (payload.sdpMid as string | null) ?? undefined,
                sdpMLineIndex: (payload.sdpMLineIndex as number | null) ?? undefined
              })
            );
          } else if (type === "session-closed") {
            setConnectionState("closed");
          } else if (type === "error") {
            setError(String((payload as { message?: string }).message ?? "signaling error"));
          }
        };

        ws.onerror = () => {
          if (alive) setError("WebSocket connection failed");
        };
      } catch (e) {
        if (!alive) return;
        setError(e instanceof Error ? e.message : String(e));
        setConnectionState("failed");
      }
    };

    run();

    return () => {
      alive = false;
      cleanup();
    };
  }, [sessionId, settings, enabled]);

  return {
    connectionState,
    remoteStream,
    sessionMeta,
    error
  };
}
