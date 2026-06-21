import { AppSettings, IceServerConfig, SessionSummary } from "@/types/session";
import { tierSemanticColor } from "@/theme";

export function parseIceServers(text: string): IceServerConfig[] {
  const trimmed = text.trim();
  if (!trimmed) {
    return [{ urls: "stun:stun.l.google.com:19302" }];
  }
  if (trimmed.startsWith("[")) {
    try {
      const parsed = JSON.parse(trimmed) as IceServerConfig[];
      if (Array.isArray(parsed) && parsed.length > 0) {
        return parsed;
      }
    } catch {
      // fall through to line-based parsing
    }
  }
  return trimmed
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((url) => ({ urls: url }));
}

export async function fetchSessions(settings: AppSettings): Promise<SessionSummary[]> {
  const headers: Record<string, string> = {};
  if (settings.caregiverToken) {
    headers.Authorization = `Bearer ${settings.caregiverToken}`;
  }
  const res = await fetch(`${settings.signalingHttpBase.replace(/\/$/, "")}/sessions`, {
    headers
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  const json = (await res.json()) as { sessions?: SessionSummary[] };
  return Array.isArray(json.sessions) ? json.sessions : [];
}

export function buildWsUrl(settings: AppSettings): string {
  const base = settings.signalingWsBase.replace(/\/$/, "");
  if (!settings.caregiverToken) {
    return base;
  }
  const sep = base.includes("?") ? "&" : "?";
  return `${base}${sep}token=${encodeURIComponent(settings.caregiverToken)}`;
}

export function formatTime(ms: number): string {
  if (!ms) return "—";
  return new Date(ms).toLocaleString();
}

export function tierColor(tier?: string): string {
  return tierSemanticColor(tier);
}
