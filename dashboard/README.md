# KineticPulse Web Monitoring Dashboard

> **Architecture:** [docs/SERVER_ARCHITECTURE.md](../docs/SERVER_ARCHITECTURE.md)  
> **Jetson deploy:** [docs/JETSON_DEPLOY.md](../docs/JETSON_DEPLOY.md) — use [`../bootstrap.sh`](../bootstrap.sh) for one-shot edge + signaling setup.

This folder contains:

- Next.js monitoring and caregiver web UI (`app/`)
- Mock-first monitoring API (`app/api/monitoring/route.ts`)
- Normalized monitoring model and adapters (`lib/monitoring/`)
- SQLite operational event persistence
- WebSocket signaling server (`server/signaling-server.js`)
- TURN deployment templates (`deploy/`)

## Run the monitoring dashboard

The MVP defaults to mock mode and does not require the Python runtime or hardware.
The environment example is located at `dashboard/.env.example`. From the repository
root, create the local file with placeholder development values using:

```powershell
Copy-Item dashboard/.env.example dashboard/.env.local
```

Edit `dashboard/.env.local` only when you need to change the SQLite path, retention,
recent-event limit, monitoring source, or signaling endpoints. Do not commit secrets.

SQLite is used because this is currently a single-device prototype with modest
operational event volume. It provides durable local history without introducing an
ORM or an external database service.

```bash
cd dashboard
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The dashboard polls its local
monitoring endpoint every three seconds.

Useful checks:

```bash
npm run typecheck
npm run lint
npm test
npm run build
```

## Mock mode

Mock mode is selected when `MONITORING_DATA_MODE` is absent or set to `mock`.
A development-only selector provides these scenarios:

- `normal`
- `resting`
- `possible_fall`
- `confirmed_fall`
- `pulse_lost`
- `sensor_disconnected`

Every mock object is located in
[`lib/monitoring/mockMonitoringData.ts`](lib/monitoring/mockMonitoringData.ts).
That file documents simulated meaning, expected hardware/pipeline source, units,
ranges, null/error meaning, and the exact future mapping point for important fields.
Mock values are never embedded in UI components or stored as scenario definitions in
SQLite.

The scenario selector is hidden in production. It can be explicitly enabled with:

```bash
NEXT_PUBLIC_ENABLE_SCENARIO_SELECTOR=true
```

## Data-source architecture

Dashboard components consume only `MonitoringModel` from
[`lib/monitoring/model.ts`](lib/monitoring/model.ts). They do not know whether data
came from a mock, HTTP endpoint, ESP32, future WebSocket, in-memory store, or SQLite.

- `mockMonitoringAdapter.ts` maps the centralized mock scenarios.
- `backendMonitoringAdapter.ts` maps the future real monitoring envelope.
- `dataSources.ts` selects mock or real mode and labels event sources.
- `clientDataSource.ts` is the small browser polling boundary and can later be
  replaced by a WebSocket client without rewriting UI components.
- `EventStore` is the persistence boundary implemented by `SQLiteEventStore` and
  `InMemoryEventStore`.

The existing WebSocket endpoint is intentionally left unchanged because it carries
WebRTC offer/answer/ICE signaling rather than monitoring telemetry.

### Enable real Jetson sensor data

On the Jetson, `kineticpulse` publishes vitals at `GET /monitoring` (default
port **8790**, `config.yaml` → `monitoring:`). Point the dashboard at it:

```bash
MONITORING_DATA_MODE=real
KINETICPULSE_MONITORING_HTTP_URL=http://<jetson-host>:8790/monitoring
```

`./bootstrap.sh` writes these into `deploy/handoff/caregiver.env` and
`dashboard/.env.local` automatically. Keep `mock` mode for UI work without hardware.

## Expected monitoring contract

The upstream endpoint should return this envelope. Snapshot names intentionally match
`kineticpulse.fusion.engine.FusionSnapshot` and existing alert payload conventions.

```json
{
  "subject_id": "resident-001",
  "location": "Living room",
  "system": { "connection": "connected" },
  "sensor": { "connection": "connected" },
  "snapshot": {
    "decision": {
      "tier": "none",
      "scenario": "monitoring",
      "reason": "No fall signatures detected."
    },
    "pose": "upright",
    "accel": "quiet",
    "hr": "resting",
    "latest_hr_bpm": 72,
    "latest_accel_g": 1.01,
    "detector_class": "stand",
    "detector_conf": 0.96,
    "action_class": "stand",
    "action_conf": 0.93,
    "timestamp_ms": 1770000000000
  },
  "voice": { "status": "not_required" },
  "alert_dispatch": { "status": "idle" },
  "events": []
}
```

Allowed emergency levels are the existing values `none`, `tier_0_dismiss`,
`tier_1_verify`, `tier_2_seizure`, and `tier_2_cardiac`. Vision classes are
`fallen`, `falling`, `stand`, and `sitting`; `null` means no camera result.

Jetson `MonitoringPublisher` fills `system`, `sensor` (TCP/BLE/mock link), and
`snapshot` from `FusionEngine.latest`. Voice / alert-dispatch progress and rich
`events[]` are still stubbed (`not_required` / `idle` / `[]`); the dashboard SQLite
store builds history from polled snapshots.

## SQLite operational history

The API writes each emitted normalized monitoring event to SQLite before returning the
unchanged `MonitoringModel` response. UI components remain unaware of persistence.
`InMemoryEventStore` is retained for tests and explicit fallback use.

### Location and configuration

The local default is:

```text
dashboard/runtime/monitoring.db
```

Override it with `MONITORING_DB_PATH`. Relative paths resolve from the dashboard
process working directory. The runtime directory and SQLite `.db`, `.db-wal`, and
`.db-shm` files are ignored by Git.

- `MONITORING_EVENT_LIMIT=30` bounds recent events in API responses.
- `MONITORING_RETENTION_DAYS=30` removes rows older than 30 days once when the
  SQLite store opens. Cleanup is not run on every poll.

### Schema and migrations

`schema_migrations` records applied integer migration versions. Migration 1 creates
`monitoring_events` with:

- stable record and source event IDs;
- `source` (`mock`, `jetson`, or `unknown`);
- UTC ISO-8601 event and creation timestamps;
- event category, scenario, severity, title, and detail;
- system/device connection status, heart rate, IMU/vision state, fall confidence and
  detection, emergency tier, voice status, and alert status;
- optional normalized payload JSON for forward compatibility.

The event timestamp is indexed for newest-first history. SQLite foreign keys,
busy timeout, WAL journal mode, and normal synchronous mode are enabled at startup
where supported.

### Deduplication

The primary record ID is deterministic: `<source>:<source_event_id>`. A unique
`(source, source_event_id)` index provides a second database-level guard. Repeated
three-second polling therefore does not insert duplicate mock or Jetson events. Mock
scenario definitions themselves remain only in `mockMonitoringData.ts`; only their
emitted normalized events are persisted with `source=mock`.

### Inspect or reset locally

With the SQLite CLI installed:

```bash
sqlite3 runtime/monitoring.db ".tables"
sqlite3 runtime/monitoring.db "SELECT source, event_timestamp_utc, event_type, emergency_tier FROM monitoring_events ORDER BY event_timestamp_utc DESC LIMIT 20;"
```

To reset local history, stop the dashboard and remove `runtime/monitoring.db` plus any
matching `-wal` and `-shm` files. The schema is recreated automatically on next start.
This reset is destructive and cannot be recovered unless the database was backed up.

### Future Jetson writes

The future Jetson endpoint continues through `BackendMonitoringDataSource` and
`backendMonitoringAdapter.ts`. That adapter produces the same normalized model, while
the API labels emitted records `source=jetson` and writes through the same `EventStore`
interface. No UI or public response-contract change is needed.

SQLite is appropriate for the current single-process, single-device prototype. A
multi-server deployment, several devices/users, centralized filtering, or formal audit
retention should move the same repository contract to PostgreSQL or another managed
database rather than sharing a SQLite file across servers.

## Existing caregiver signaling

The existing caregiver session and WebRTC signaling architecture remains available:

```bash
# Set JETSON_SIGNAL_TOKEN, CAREGIVER_SIGNAL_TOKEN, and ALLOWED_ORIGINS first.
npm run signal
```

Defaults remain HTTP `http://localhost:8787/sessions` and WebSocket
`ws://localhost:8787/ws`. Production signaling should use HTTPS/WSS or a private
Tailscale network and configured TURN infrastructure.
