# Architecture Overview

## Main System Components

### `api/server.py`
FastAPI application with:
- Parking pipeline (camera → YOLO → occupancy state)
- System monitoring endpoint (`/api/v1/system`)
- History DB for parking data
- Activity-based pipeline lifecycle (idle/running/heartbeat)

### `api/system_stats.py`
In-memory system resource collector using `psutil`:
- Collects CPU, RAM, disk, network, temperature every call
- Stores last 300 data points in a ring buffer (deque)
- No database — pure in-memory history
- Exposed via `/api/v1/system`

### `api/database.py`
SQLite persistence for parking occupancy history (not for system stats).

### `web/`
Static frontend (HTML + JS) served at `/web/`:
- **Purpose**: Server resource monitoring dashboard
- Shows: hostname, OS, architecture, CPU/RAM/disk/network/temp
- Real-time charts (CPU %, RAM %) with ~5 min visible history
- Per-core CPU display
- Polls `/api/v1/system` every 2 seconds
- No external dependencies (vanilla JS + Canvas charts)

### `parking/`
Core CV pipeline: `pipeline.py` → `detector.py` (YOLO) → `analyzer.py` → `transformer.py`

### `config.py`
Pydantic-based config loading from `.env`

## Deployment
- Dockerfile runs `uvicorn api.server:app` on port 8000
- `/web/` served as static files
- `/assets/` also mounted for parking map SVGs

## Key Endpoints
| Path | Purpose |
|------|---------|
| `/api/v1/state` | Latest parking snapshot (marks client active) |
| `/api/v1/health` | Pipeline + camera health |
| `/api/v1/history` | Historical parking data from DB |
| `/api/v1/system` | **System resource metrics + history (in-memory)** |
| `/web/` | Static monitoring dashboard |
