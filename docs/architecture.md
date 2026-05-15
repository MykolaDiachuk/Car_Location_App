# Architecture overview

Parking Monitor is a small, single-camera Python service. Four loosely
coupled components do all the work:

```
                       ┌────────────────┐
   RTSP camera ──────▶ │  Detector      │  YOLOv11 → list of [x1,y1,x2,y2,conf]
                       └─────┬──────────┘
                             │
                       ┌─────▼──────────┐
                       │  Tracker       │  K-of-N hysteresis (optional)
                       │  (carry-over)  │  smooths single-frame YOLO misses
                       └─────┬──────────┘
                             │
                       ┌─────▼──────────┐
                       │  Transformer   │  homography → Bird's Eye View
                       └─────┬──────────┘
                             │
                       ┌─────▼──────────┐
                       │  Analyzer      │  marks occupied cells, grid-scans
                       │                │  parking_mask.png for free spots
                       └─────┬──────────┘
                             │
                             ▼
                   ParkingState  →  HTTP API  →  Web dashboard
                                                 SQLite history DB
```

Source files:

- `parking/detector.py` — YOLO wrapper + post-detection dedupe
- `parking/tracker.py` — `SpotStateTracker` (K-of-N hysteresis with carry-over)
- `parking/transformer.py` — perspective transform to BEV
- `parking/analyzer.py` — occupancy logic, free-spot grid scan
- `parking/pipeline.py` — wires the four together
- `parking/models.py` — Pydantic data classes (`ParkingState`, `ParkingSpot`, …)

## HTTP layer (`api/`)

| Module | Role |
|---|---|
| `server.py` | FastAPI app, CORS, lifespan, router mounting. ~120 lines. |
| `settings.py` | Parses env vars into an immutable `Settings` dataclass. |
| `state_store.py` | Thread-safe shared state (latest snapshot, activity timer, health counters). |
| `pipeline_worker.py` | Background thread that runs the pipeline; activity-driven idle/active state machine. |
| `database.py` | SQLite history storage with WAL mode for concurrent R/W. |
| `system_stats.py` | Host CPU/RAM/disk metrics for the dashboard. |
| `routes/` | One file per endpoint (`state`, `health`, `history`, `system`, `index`). |

## Activity-driven pipeline

The pipeline runs continuously only while at least one client has polled
`/api/v1/state` within `IDLE_TIMEOUT` (default 30 s). When idle, the camera
is released — no resources held.

```
Client polls /api/v1/state
  → store.mark_activity() resets the idle timer and wakes the worker
  → worker connects to the camera, processes frames at ANALYSIS_INTERVAL
  → IDLE_TIMEOUT s with no polls → camera released, worker sleeps
```

On the first poll after idle, the server returns the **last cached
snapshot** immediately (potentially stale, flagged via `stale: true`).
Fresh data arrives on the next poll ~1 s later.

## Heartbeat snapshots

If the worker stays idle for `HEARTBEAT_INTERVAL` seconds (default 1 h) it
briefly wakes the camera, grabs a single frame, writes a force-record to
the DB, and goes back to sleep. This:

- Keeps `parking_snapshots` continuous (no multi-hour gaps overnight).
- Guarantees that a returning visitor sees data no older than the heartbeat
  interval, even before their first poll triggers a full wake.

Active processing resets the heartbeat clock, so the system never
double-snapshots right after clients leave.

## Temporal hysteresis

YOLO occasionally misses a stationary car for a single frame and finds it
again on the next. The optional `SpotStateTracker` absorbs these misses by
clustering bboxes across the last N frames and emitting any cluster that
spans ≥ K frames — using the most recent sighting's position (carry-over).

See [temporal-smoothing.md](temporal-smoothing.md) for the algorithm and
tuning advice.

## History database

SQLite, single file at `DB_PATH`. Used only by the API server (the
standalone `monitor.py` does not write to it).

```sql
CREATE TABLE parking_snapshots (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp         TEXT    NOT NULL,         -- UTC, 'YYYY-MM-DD HH:MM:SS'
    total_spots       INTEGER NOT NULL,
    occupied          INTEGER NOT NULL,
    free              INTEGER NOT NULL,
    occupancy_percent REAL    NOT NULL
);
CREATE INDEX idx_snapshots_ts ON parking_snapshots(timestamp);
```

**Thread safety:** each thread gets its own `sqlite3.Connection` via
`threading.local()`. WAL journal mode allows concurrent reads (HTTP request
threads) and writes (pipeline worker thread) without blocking.

**Persistence across deploys:** mount `DB_PATH` as a Docker volume — see
[deployment.md](deployment.md).

`/api/v1/history` auto-aggregates rows on read (1 min / 5 min / 30 min /
2 h buckets) so the response stays at ~120–360 points regardless of the
queried span.
