"use strict";

const http = require("http");
const crypto = require("crypto");
const { URL } = require("url");
const WebSocket = require("ws");

const HOST = process.env.SIGNAL_HOST || "0.0.0.0";
const PORT = Number(process.env.SIGNAL_PORT || 8787);
const JETSON_TOKEN = process.env.JETSON_SIGNAL_TOKEN || "";
const CAREGIVER_TOKEN = process.env.CAREGIVER_SIGNAL_TOKEN || "";
const SESSION_TTL_MS = Number(process.env.SESSION_TTL_MS || 5 * 60 * 1000);
const ALLOWED_ORIGINS = (process.env.ALLOWED_ORIGINS || "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

/** @type {Map<string, any>} */
const sessions = new Map();

function nowMs() {
  return Date.now();
}

function json(res, status, body) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}

function bearerFromHeader(authHeader) {
  if (!authHeader || !authHeader.startsWith("Bearer ")) return "";
  return authHeader.slice("Bearer ".length).trim();
}

function secureEq(a, b) {
  if (!a || !b) return false;
  const ba = Buffer.from(a);
  const bb = Buffer.from(b);
  if (ba.length !== bb.length) return false;
  return crypto.timingSafeEqual(ba, bb);
}

function authRole(req) {
  const urlObj = new URL(req.url, "http://localhost");
  const qToken = urlObj.searchParams.get("token") || "";
  const hToken = bearerFromHeader(req.headers.authorization || "");
  const token = qToken || hToken;
  if (JETSON_TOKEN && secureEq(token, JETSON_TOKEN)) return "jetson";
  if (CAREGIVER_TOKEN && secureEq(token, CAREGIVER_TOKEN)) return "caregiver";
  return null;
}

function originAllowed(origin) {
  if (ALLOWED_ORIGINS.length === 0) return true;
  if (!origin) return false;
  return ALLOWED_ORIGINS.includes(origin);
}

function cleanExpiredSessions() {
  const now = nowMs();
  for (const [id, s] of sessions.entries()) {
    if (now - (s.updated_at_ms || s.created_at_ms) > SESSION_TTL_MS) {
      if (s.viewer_ws) s.viewer_ws.close();
      if (s.jetson_ws) s.jetson_ws.close();
      sessions.delete(id);
    }
  }
}

setInterval(cleanExpiredSessions, 15_000).unref();

const server = http.createServer((req, res) => {
  const origin = req.headers.origin;
  if (!originAllowed(origin)) return json(res, 403, { ok: false, error: "origin_forbidden" });
  if (origin) {
    res.setHeader("Access-Control-Allow-Origin", origin);
    res.setHeader("Vary", "Origin");
  }
  res.setHeader("Access-Control-Allow-Headers", "Authorization, Content-Type");
  if (req.method === "OPTIONS") {
    res.writeHead(204);
    res.end();
    return;
  }

  const role = authRole(req);
  if (!role) return json(res, 401, { ok: false, error: "unauthorized" });

  if (req.method === "GET" && req.url.startsWith("/sessions")) {
    const list = Array.from(sessions.values()).map((s) => ({
      session_id: s.session_id,
      status: s.status,
      created_at_ms: s.created_at_ms,
      updated_at_ms: s.updated_at_ms,
      meta: s.meta || {}
    }));
    return json(res, 200, { ok: true, sessions: list });
  }
  return json(res, 404, { ok: false, error: "not_found" });
});

const wss = new WebSocket.Server({ noServer: true });

function send(ws, type, payload) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type, payload }));
}

server.on("upgrade", (req, socket, head) => {
  if (!req.url.startsWith("/ws")) {
    socket.destroy();
    return;
  }
  if (!originAllowed(req.headers.origin)) {
    socket.write("HTTP/1.1 403 Forbidden\r\n\r\n");
    socket.destroy();
    return;
  }
  const role = authRole(req);
  if (!role) {
    socket.write("HTTP/1.1 401 Unauthorized\r\n\r\n");
    socket.destroy();
    return;
  }
  req._signalRole = role;
  wss.handleUpgrade(req, socket, head, (ws) => {
    ws._signalRole = role;
    wss.emit("connection", ws, req);
  });
});

wss.on("connection", (ws) => {
  ws.on("message", (raw) => {
    let msg;
    try {
      msg = JSON.parse(String(raw));
    } catch {
      return send(ws, "error", { message: "invalid_json" });
    }
    const type = msg?.type;
    const payload = msg?.payload || {};
    const role = ws._signalRole;

    if (type === "create-session") {
      if (role !== "jetson") return send(ws, "error", { message: "forbidden" });
      const sid = String(payload.session_id || "");
      if (!sid || !payload.offer) return send(ws, "error", { message: "bad_request" });
      const session = {
        session_id: sid,
        created_at_ms: nowMs(),
        updated_at_ms: nowMs(),
        status: "waiting_viewer",
        meta: payload.meta || {},
        offer: payload.offer,
        jetson_ws: ws,
        viewer_ws: null
      };
      sessions.set(sid, session);
      return send(ws, "session-created", { session_id: sid });
    }

    if (type === "join-session") {
      if (role !== "caregiver") return send(ws, "error", { message: "forbidden" });
      const sid = String(payload.session_id || "");
      const s = sessions.get(sid);
      if (!s) return send(ws, "error", { message: "session_not_found" });
      if (s.viewer_ws && s.viewer_ws.readyState === WebSocket.OPEN && s.viewer_ws !== ws) {
        return send(ws, "error", { message: "viewer_already_attached" });
      }
      s.viewer_ws = ws;
      s.status = "viewer_joined";
      s.updated_at_ms = nowMs();
      send(ws, "offer", { session_id: sid, offer: s.offer, meta: s.meta });
      return;
    }

    if (type === "answer") {
      if (role !== "caregiver") return send(ws, "error", { message: "forbidden" });
      const sid = String(payload.session_id || "");
      const s = sessions.get(sid);
      if (!s || !s.jetson_ws) return send(ws, "error", { message: "session_not_found" });
      s.status = "connected";
      s.updated_at_ms = nowMs();
      return send(s.jetson_ws, "answer", { session_id: sid, answer: payload.answer });
    }

    if (type === "ice-candidate") {
      const sid = String(payload.session_id || "");
      const s = sessions.get(sid);
      if (!s) return send(ws, "error", { message: "session_not_found" });
      s.updated_at_ms = nowMs();
      if (role === "jetson" && s.viewer_ws) {
        return send(s.viewer_ws, "ice-candidate", payload);
      }
      if (role === "caregiver" && s.jetson_ws) {
        return send(s.jetson_ws, "ice-candidate", payload);
      }
      return;
    }

    if (type === "close-session") {
      const sid = String(payload.session_id || "");
      const s = sessions.get(sid);
      if (!s) return;
      send(s.viewer_ws, "session-closed", { session_id: sid });
      send(s.jetson_ws, "session-closed", { session_id: sid });
      sessions.delete(sid);
      return;
    }

    send(ws, "error", { message: "unknown_message_type" });
  });

  ws.on("close", () => {
    for (const [sid, s] of sessions.entries()) {
      if (s.jetson_ws === ws || s.viewer_ws === ws) {
        if (s.jetson_ws && s.jetson_ws !== ws) send(s.jetson_ws, "session-closed", { session_id: sid });
        if (s.viewer_ws && s.viewer_ws !== ws) send(s.viewer_ws, "session-closed", { session_id: sid });
        sessions.delete(sid);
      }
    }
  });
});

server.listen(PORT, HOST, () => {
  console.log(`signaling server listening on http://${HOST}:${PORT}`);
  console.log(`ws endpoint: ws://${HOST}:${PORT}/ws`);
});
