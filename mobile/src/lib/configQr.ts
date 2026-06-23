import { AppSettings, DEFAULT_SETTINGS } from "@/types/session";

/** QR payload written by `deploy/scripts/write_caregiver_handoff.py`. */
export type CaregiverConfigQrV1 = {
  v: 1;
  signalingHttpBase: string;
  signalingWsBase: string;
  caregiverToken: string;
  iceServersText?: string;
};

function isNonEmptyString(v: unknown): v is string {
  return typeof v === "string" && v.trim().length > 0;
}

function fromV1(obj: CaregiverConfigQrV1): AppSettings {
  return {
    signalingHttpBase: obj.signalingHttpBase.trim(),
    signalingWsBase: obj.signalingWsBase.trim(),
    caregiverToken: obj.caregiverToken.trim(),
    iceServersText: (obj.iceServersText ?? DEFAULT_SETTINGS.iceServersText).trim()
  };
}

function parseJsonPayload(text: string): AppSettings | null {
  try {
    const obj = JSON.parse(text) as Partial<CaregiverConfigQrV1>;
    if (obj.v !== 1) return null;
    if (
      !isNonEmptyString(obj.signalingHttpBase) ||
      !isNonEmptyString(obj.signalingWsBase) ||
      !isNonEmptyString(obj.caregiverToken)
    ) {
      return null;
    }
    return fromV1(obj as CaregiverConfigQrV1);
  } catch {
    return null;
  }
}

function base64UrlToString(payload: string): string {
  const padded = payload.replace(/-/g, "+").replace(/_/g, "/");
  const pad = padded.length % 4 === 0 ? "" : "=".repeat(4 - (padded.length % 4));
  const binary = atob(padded + pad);
  const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

/** `kineticpulse://setup?payload=<base64url(json)>` */
function parseDeepLink(text: string): AppSettings | null {
  const trimmed = text.trim();
  if (!trimmed.startsWith("kineticpulse://")) return null;
  try {
    const url = new URL(trimmed);
    const path = url.pathname.replace(/^\//, "");
    if (url.hostname !== "setup" && path !== "setup") return null;
    const payload = url.searchParams.get("payload");
    if (!payload) return null;
    return parseJsonPayload(base64UrlToString(payload));
  } catch {
    return null;
  }
}

/** Plain-text `caregiver.env` lines inside a QR. */
function parseEnvLines(text: string): AppSettings | null {
  const map: Record<string, string> = {};
  for (const line of text.split(/\r?\n/)) {
    const t = line.trim();
    if (!t || t.startsWith("#")) continue;
    const eq = t.indexOf("=");
    if (eq < 1) continue;
    map[t.slice(0, eq).trim()] = t.slice(eq + 1).trim();
  }
  const http = map.NEXT_PUBLIC_SIGNALING_HTTP_BASE;
  const ws = map.NEXT_PUBLIC_SIGNALING_WS_BASE;
  const token = map.NEXT_PUBLIC_CAREGIVER_TOKEN;
  if (!http || !ws || !token) return null;
  return {
    signalingHttpBase: http,
    signalingWsBase: ws,
    caregiverToken: token,
    iceServersText: DEFAULT_SETTINGS.iceServersText
  };
}

export function parseConfigQrPayload(raw: string): AppSettings | null {
  const text = raw.trim();
  if (!text) return null;
  return parseJsonPayload(text) ?? parseDeepLink(text) ?? parseEnvLines(text);
}
