# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

Real-time parking lot occupancy monitoring using YOLOv11 vehicle detection and Bird's Eye View (BEV) perspective transformation. Designed for unstructured parking lots without lane markings.

## Commands

```bash
# Install backend dependencies
pip install -r requirements.txt

# Install configurator dependencies (separate environment recommended)
pip install -r parking_configurator/requirements.txt

# Run real-time monitor (main application)
python monitor.py

# Run GUI setup tool
python parking_configurator/main.py

# Calibration tools (run individually as needed — owner use only)
python tools/capture_frame.py              # Grab frame from RTSP camera
python tools/test_connection.py            # Test RTSP connectivity
python tools/find_bev_points.py            # Interactive SRC_POINTS selector
python tools/generate_bev.py               # Generate static BEV image
python tools/edit_parking_mask.py          # Paint allowed/forbidden zones
python tools/edit_orientation_zones.py     # Paint parallel/perpendicular zones
python tools/test_bev_camera.py            # Live BEV preview
```

No formal test suite exists. Manual testing is done via `tools/test_connection.py` and visual inspection of `monitor.py` output.

> **`tools/` and `parking_configurator/` are owner-only.** Do not read or modify files in these directories unless explicitly asked.

## Architecture

Four independent components share `config.py` as the central configuration source.

### 1. Backend Pipeline (`parking/`)

**Data flow:**
```
Camera Frame (RTSP)
  → VehicleDetector (YOLO11n) → list of [x1,y1,x2,y2,confidence]
  → PerspectiveTransformer (homography) → BEV image + projected points
  → ParkingAnalyzer (mask-based grid scan) → annotated image + ParkingState
```

- `parking/detector.py` — wraps Ultralytics YOLO; filters by `VEHICLE_CLASSES` and `CONF_THRESHOLD`. After detection, `_dedupe_overlapping()` drops a smaller bbox if its intersection with a larger one covers ≥ `OVERLAP_THRESHOLD` of the smaller bbox's area (default 0.8) — catches duplicate detections on the same car that NMS misses when one box is mostly contained in another.
- `parking/transformer.py` — computes homography from `SRC_POINTS` → BEV corners; `transform_point()` returns the raw projected point (may fall outside the BEV frame — callers clamp as needed)
- `parking/analyzer.py` — loads `parking_mask.png` and `orientation_zones.png`; marks occupied areas using car dimensions, then grid-scans remaining white pixels for free spots
- `parking/pipeline.py` — `ParkingPipeline.process_frame()` orchestrates the three above; returns `AnalysisResult` (bev view, annotated view, `ParkingState`)
- `parking/models.py` — Pydantic models: `ParkingSpot`, `ParkingState`, `SpotStatus`, `SpotOrientation`, `NormalizedPoint`, `HistoryPoint`, `HistoryResponse`
- `monitor.py` — RTSP connection with retry, runs pipeline on a configurable interval, displays result in OpenCV window (`q`=quit, `s`=save screenshot)

### 2. HTTP API (`api/`)

FastAPI server started via `uvicorn api.server:app --host 0.0.0.0 --port 8000`.

#### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/state` | Current parking snapshot. Marks client as active — keeps the pipeline running. Returns `503` only on cold start. |
| `GET` | `/api/v1/history` | Historical occupancy for chart rendering. Does **not** mark activity. |
| `GET` | `/api/v1/health` | Operational health check. Does not mark activity (safe for external monitors). |
| `GET` | `/` | API index with links to all endpoints and `/docs`. |
| `GET` | `/web/` | Frontend SPA (served from `web/`). |
| `GET` | `/assets/` | Static assets (BEV maps, etc.). |

#### `GET /api/v1/state` → `StateResponse`

```json
{
  "timestamp": "2025-01-01T12:00:00Z",
  "age_seconds": 0.8,
  "stale": false,
  "pipeline_status": "running",
  "bev_width": 1200,
  "bev_height": 800,
  "total_spots": 15,
  "occupied": 8,
  "free": 7,
  "occupancy_percent": 53.3,
  "spots": [
    {
      "id": 0,
      "status": "occupied",
      "orientation": "perpendicular",
      "center_bev": { "x": 0.48, "y": 0.55 },
      "bbox_bev": { "x1": 273, "y1": 360, "x2": 423, "y2": 440 },
      "confidence": 0.91
    }
  ]
}
```

`stale: true` when snapshot age exceeds `STALE_THRESHOLD` (default 10 s).  
`pipeline_status`: `"running"` | `"idle"` | `"starting"` | `"error"`.

#### `GET /api/v1/history` → `HistoryResponse`

Query parameters (provide **either** `period` **or** `from`/`to`):

| Param | Type | Example | Description |
|-------|------|---------|-------------|
| `period` | string | `1h`, `24h`, `7d`, `30d` | Lookback window from now |
| `from` | ISO 8601 datetime | `2025-01-01T00:00:00Z` | Start of custom range |
| `to` | ISO 8601 datetime | `2025-01-02T00:00:00Z` | End of custom range (defaults to now) |

Default when no params: last 24 hours. Maximum range: 90 days.

Aggregation granularity is chosen automatically to keep ~120–360 points:

| Time span | Bucket | ~Points |
|-----------|--------|---------|
| ≤ 1 h | raw (no aggregation) | ~30 |
| ≤ 6 h | 1 min averages | ~360 |
| ≤ 24 h | 5 min averages | ~288 |
| ≤ 7 d | 30 min averages | ~336 |
| > 7 d | 2 h averages | ~360 |

```json
{
  "period_from": "2025-01-01T00:00:00Z",
  "period_to":   "2025-01-08T00:00:00Z",
  "bucket_seconds": 1800,
  "point_count": 336,
  "points": [
    {
      "timestamp": "2025-01-01T00:00:00Z",
      "total_spots": 15,
      "occupied": 4,
      "free": 11,
      "occupancy_percent": 26.7
    }
  ]
}
```

`bucket_seconds: 0` means raw data (no averaging applied).

#### `GET /api/v1/health` → `HealthResponse`

```json
{
  "status": "ok",
  "uptime_seconds": 3600.0,
  "pipeline": {
    "status": "running",
    "frames_processed": 3600,
    "errors": 0,
    "last_error": null
  },
  "camera": {
    "connected": true,
    "last_frame_at": "2025-01-01T12:00:00Z"
  },
  "bev_width": 1200,
  "bev_height": 800
}
```

`status`: `"ok"` | `"degraded"` | `"error"` | `"starting"`.

#### Activity-based pipeline + idle heartbeat

The pipeline runs continuously while clients actively poll `/api/v1/state`. After `IDLE_TIMEOUT` seconds of no polls the camera is released. The first poll after idle wakes the worker; a fresh snapshot is ready within ~2 seconds.

To prevent multi-hour gaps in `parking_snapshots` (e.g. overnight) and to make sure a returning visitor sees recent data instead of yesterday's, the worker also takes a single **heartbeat snapshot** every `HEARTBEAT_INTERVAL` seconds while idle: connect → discard a few warm-up frames → grab one frame → process → write to DB with `force_record=True` → release camera. Active processing resets the heartbeat clock so we don't double-snapshot right after clients leave. Set `HEARTBEAT_INTERVAL=0` to disable.

#### Environment variables (`api/server.py`)

| Variable | Default | Description |
|----------|---------|-------------|
| `CAMERA_URL` | — | RTSP stream URL (required unless `MOCK_MODE=true`) |
| `MOCK_MODE` | `false` | Skip camera/YOLO; emit synthetic state |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `ANALYSIS_INTERVAL` | `1.0` | Seconds between pipeline runs while active |
| `IDLE_TIMEOUT` | `30.0` | Seconds of inactivity before pipeline sleeps |
| `STALE_THRESHOLD` | `10.0` | Seconds after which snapshot is marked stale |
| `DB_PATH` | `/data/parking_history.db` | SQLite file path |
| `RECORD_INTERVAL` | `120.0` | Seconds between DB writes while active |
| `RETENTION_DAYS` | `90` | Auto-delete snapshots older than N days on startup |
| `HEARTBEAT_INTERVAL` | `3600.0` | Seconds between idle-time background snapshots (`0` disables) |

### 3. History Database (`api/database.py`)

SQLite, one file at `DB_PATH`. Used only by the API server — `monitor.py` does not write to it.

**Schema:**

```sql
CREATE TABLE parking_snapshots (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp         TEXT    NOT NULL,   -- UTC, format: 'YYYY-MM-DD HH:MM:SS'
    total_spots       INTEGER NOT NULL,
    occupied          INTEGER NOT NULL,
    free              INTEGER NOT NULL,
    occupancy_percent REAL    NOT NULL
);
CREATE INDEX idx_snapshots_ts ON parking_snapshots(timestamp);
```

**Key functions:**

| Function | Description |
|----------|-------------|
| `init_db(path)` | Create file + table + index if not exist. Called at server startup. |
| `record_snapshot(state)` | Insert one row. Called from `_set_state()` at most every `RECORD_INTERVAL` s. |
| `query_history(from_dt, to_dt)` | Return rows with auto-selected aggregation bucket. |
| `cleanup_old_data(days)` | Delete rows older than N days. Called at startup. |
| `get_snapshot_count()` | Total row count (logged at startup for diagnostics). |

**Thread safety:** each thread gets its own `sqlite3.Connection` via `threading.local()`. WAL journal mode (`PRAGMA journal_mode=WAL`) allows concurrent reads (API request threads) and writes (pipeline worker thread) without blocking.

**Persistence across deploys:** the DB file is stored on the Raspberry Pi host at `/home/mykola/parking-data/parking_history.db` and bind-mounted into the container as `-v /home/mykola/parking-data:/data`. `docker rm` + `docker run` during CI/CD redeploy does not touch this directory.

### 4. Static Assets (`assets/`)

- `parking_mask.png` — grayscale: white = parking allowed, black = forbidden (flowerbeds, exits, etc.)
- `orientation_zones.png` — color-coded: green = parallel spots, blue = perpendicular spots

These are consumed by `ParkingAnalyzer` at startup. Edit them with the tools or the configurator.

### 5. Parking Configurator (`parking_configurator/`) — owner-only

> **Do not read or modify files in `parking_configurator/` or `tools/` unless explicitly asked.** These directories are for the owner's personal use and manual testing only — they are not part of the core backend and should be treated as off-limits by default.



PyQt5 GUI with 5 tabs driven by a shared `AppState` dataclass (`app/state.py`). Tabs are in `app/tabs/`:
- `camera.py` — RTSP URL builder, live preview, frame capture
- `bev.py` — drag 4 corner points to set `SRC_POINTS`, live BEV preview
- `paint_mask.py` — reusable brush widget used by both mask and zone tabs
- `map_builder.py` — place/resize/rotate spots and borders, exports `parking_map.svg` and `spots.json`

`app/window.py` (`MainWindow`) owns the `QTabWidget` and passes `AppState` to all tabs.

### 6. Configuration (`config.py`)

All settings live in the `ParkingConfig` class. Key values to know when debugging:

| Setting | Purpose |
|---|---|
| `SRC_POINTS` | 4 camera points defining the BEV quad (can be negative/outside frame) |
| `BEV_WIDTH`, `BEV_HEIGHT` | Output BEV canvas size (default 1200×800) |
| `CAR_WIDTH`, `CAR_HEIGHT` | Constant car footprint in BEV pixels (150×80) — no perspective correction |
| `CHECK_STEP` | Grid scan stride for free spot detection (default 20px) |
| `CAMERA_URL` | RTSP connection string |
| `VEHICLE_CLASSES` | YOLO class IDs: `[2, 3, 5, 7]` = car, motorcycle, bus, truck |
| `CONF_THRESHOLD` | Minimum YOLO detection confidence (default 0.4) |
| `OVERLAP_THRESHOLD` | IoSmaller threshold for duplicate-bbox suppression (default 0.8; `1.0` disables) |

### Calibration Workflow

When setting up a new camera location, follow this sequence:
1. `capture_frame.py` → saves frame to `tools/input/`
2. `find_bev_points.py` → copy resulting `SRC_POINTS` into `config.py`
3. `generate_bev.py` → verify BEV looks correct
4. `edit_parking_mask.py` → paint and save `assets/parking_mask.png`
5. `edit_orientation_zones.py` → paint and save `assets/orientation_zones.png`

Or use the Configurator GUI for an integrated workflow.

## Known Issues

- **Spot count flicker** — grid-scan finds slightly different free spots each frame; no temporal hysteresis yet
- **Fixed car size** — `CAR_WIDTH/CAR_HEIGHT` constants don't account for perspective depth variation
- **Configurator map not persisted** — closing the window loses all placed spots/borders (no save/load)
- **`tools/` duplicates configurator** — both have mask painters; `tools/` scripts are CLI-only alternatives
- **No WebSocket** — frontend polls `/api/v1/state` every 2 s via `setInterval`; no push mechanism
