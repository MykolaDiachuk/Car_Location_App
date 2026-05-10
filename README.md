# Parking Analysis System

Intelligent parking lot occupancy monitoring using YOLOv11 vehicle detection and Bird's Eye View (BEV) perspective transformation. Designed for unstructured parking lots without lane markings.

---

## Features

- **Unstructured parking** — works without lane markings or structured bays
- **Perspective correction** — Bird's Eye View transformation from an angled camera
- **Custom parking masks** — supports complex shapes: flowerbeds, exits, irregular boundaries
- **Orientation zones** — parallel and perpendicular spot detection
- **Real-time monitoring** — RTSP camera support with automatic reconnection
- **HTTP API** — FastAPI server exposes real-time state and occupancy history as JSON
- **Occupancy history** — SQLite database records data every 2 min; survives Docker redeploys via bind-mount
- **Web UI** — built-in dashboard with live spot overlay and time-series chart (1 h / 24 h / 7 d / 30 d)

### Technologies

- **YOLOv11** (Ultralytics) — vehicle detection
- **OpenCV** — video capture, perspective transformation
- **FastAPI + uvicorn** — HTTP API server
- **NumPy** — BEV homography and grid scan
- **Pydantic** — data models and JSON serialization

---

## Project Structure

```
Car_Location_Project/
├── config.py                    # All settings (BEV points, car size, camera URL)
├── monitor.py                   # Standalone real-time monitor (OpenCV window)
├── requirements.txt             # Backend dependencies
├── .env.example                 # Camera URL template — copy to .env
│
├── api/                         # HTTP API server
│   ├── server.py                # FastAPI app — /state, /history, /health
│   ├── database.py              # SQLite history storage (init, write, query, cleanup)
│   ├── mock_state.py            # Synthetic data generator (no camera needed)
│   ├── requirements.txt         # API-specific deps (fastapi, uvicorn)
│   └── README.md                # API endpoint specification
│
├── parking/                     # Core detection pipeline
│   ├── detector.py              # YOLOv11 wrapper
│   ├── transformer.py           # Homography → BEV
│   ├── analyzer.py              # Mask-based free spot scan
│   ├── pipeline.py              # Orchestrates detector → transformer → analyzer
│   └── models.py                # Pydantic models (ParkingState, ParkingSpot, HistoryPoint, …)
│
├── web/                         # Browser dashboard (served at /web/ by API server)
│   ├── index.html               # Stats bar, spot overlay, history chart
│   └── app.js                   # Live polling + Chart.js time-series chart
│
├── assets/                      # Masks loaded at runtime
│   ├── parking_mask.png         # White = parking allowed, black = forbidden
│   └── orientation_zones.png    # Green = parallel, blue = perpendicular
│
├── parking_configurator/        # GUI setup tool (owner-only)
│   ├── main.py                  # Entry point (PyQt5)
│   └── requirements.txt
│
└── tools/                       # Calibration scripts (owner-only)
    ├── capture_frame.py
    ├── find_bev_points.py
    ├── generate_bev.py
    ├── edit_parking_mask.py
    └── edit_orientation_zones.py
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
pip install fastapi uvicorn[standard] aiofiles   # for the API server
```

Or install everything at once:

```bash
pip install -r requirements.txt -r api/requirements.txt
```

### 2. Configure camera URL

```bash
cp .env.example .env
```

Edit `.env`:

```
CAMERA_URL=rtsp://user:password@192.168.0.1:554/stream
```

`.env` is gitignored — credentials never end up in version control.

### 3. Verify camera connection (optional)

```bash
python tools/test_connection.py
```

---

## Running

There are three independent ways to run the system. Pick one depending on your goal.

---

### Option A — Standalone monitor (OpenCV window)

Displays a live annotated BEV view directly on screen. No browser needed.

```bash
python monitor.py
```

Controls:
- `q` — quit
- `s` — save screenshot to `output/`

Requires a real camera (set `CAMERA_URL` in `.env`).

---

### Option B — API server + Web UI

Serves the JSON API and the browser dashboard on the same port.

```bash
uvicorn api.server:app --host 0.0.0.0 --port 8000
```

Then open:

| URL | What you get |
|---|---|
| `http://localhost:8000/web/` | Live parking dashboard + history chart |
| `http://localhost:8000/docs` | Swagger UI (interactive API docs) |
| `http://localhost:8000/api/v1/state` | Raw JSON snapshot |
| `http://localhost:8000/api/v1/history?period=24h` | Occupancy history (chart data) |
| `http://localhost:8000/api/v1/health` | Pipeline health |

**Without a camera — mock mode** (useful for frontend development or testing):

```bash
# Linux / macOS
MOCK_MODE=true uvicorn api.server:app --port 8000 --reload

# Windows PowerShell
$env:MOCK_MODE="true"; uvicorn api.server:app --port 8000 --reload
```

Mock mode generates synthetic occupancy data that cycles every second — no YOLO, no camera required.

**Environment variables** (all optional, override `config.py` defaults):

| Variable | Default | Description |
|---|---|---|
| `CAMERA_URL` | from `.env` | RTSP stream |
| `MOCK_MODE` | `false` | Skip camera/YOLO, use synthetic data |
| `ANALYSIS_INTERVAL` | `1.0` | Seconds between pipeline runs |
| `IDLE_TIMEOUT` | `30.0` | Seconds before pipeline pauses (no clients) |
| `STALE_THRESHOLD` | `10.0` | Seconds before snapshot is marked stale |
| `CORS_ORIGINS` | `*` | Allowed origins for browser clients |
| `DB_PATH` | `/data/parking_history.db` | SQLite file path |
| `RECORD_INTERVAL` | `120.0` | Seconds between DB writes while active |
| `RETENTION_DAYS` | `90` | Auto-delete snapshots older than N days |
| `HEARTBEAT_INTERVAL` | `3600.0` | Seconds between background snapshots while idle (no clients). The worker briefly wakes the camera, grabs one frame, writes to DB, and goes back to sleep. Keeps history continuous and guarantees the next visitor sees data no older than this. Set to `0` to disable. |

---

### Option C — Parking Configurator (GUI)

PyQt5 desktop tool for camera setup, BEV calibration, and mask painting.

```bash
pip install -r parking_configurator/requirements.txt
python parking_configurator/main.py
```

Use this when setting up a new camera location. Workflow:
1. **Camera tab** — enter RTSP URL, preview live feed, capture a frame
2. **BEV tab** — drag 4 corner points to define the parking area, copy `SRC_POINTS` to `config.py`
3. **Mask tab** — paint allowed/forbidden zones, save `assets/parking_mask.png`
4. **Zones tab** — paint parallel/perpendicular areas, save `assets/orientation_zones.png`

---

## Configuration

All settings live in `config.py`. The most important ones:

| Setting | Default | Description |
|---|---|---|
| `SRC_POINTS` | *(calibrated)* | 4 camera points defining the BEV quad (TL → TR → BR → BL) |
| `BEV_WIDTH` | `1200` | BEV canvas width in pixels |
| `BEV_HEIGHT` | `800` | BEV canvas height in pixels |
| `CAR_WIDTH` | `150` | Car footprint width in BEV pixels |
| `CAR_HEIGHT` | `80` | Car footprint height in BEV pixels |
| `CHECK_STEP` | `20` | Grid scan stride for free spot detection |
| `CONF_THRESHOLD` | `0.3` | YOLO minimum detection confidence |
| `VEHICLE_CLASSES` | `[2,3,5,7]` | YOLO class IDs: car, motorcycle, bus, truck |

`CAMERA_URL` is read from the `CAMERA_URL` environment variable (set in `.env`).

---

## Troubleshooting

**Camera does not connect**
→ Run `python tools/test_connection.py` to verify the RTSP URL
→ Check `CAMERA_URL` in `.env`

**Spot count flickers between frames**
→ Expected — no temporal smoothing is implemented yet (known issue)

**YOLO misses cars**
→ Lower `CONF_THRESHOLD` in `config.py` (e.g. `0.3` → `0.2`)

**BEV looks distorted**
→ Recalibrate `SRC_POINTS` with `tools/find_bev_points.py` or the Configurator BEV tab

**Algorithm marks flowerbeds/exits as free spots**
→ Paint those areas black in `assets/parking_mask.png` using `tools/edit_parking_mask.py` or the Configurator

**API returns 503 on first request**
→ Normal — pipeline is starting. Keep polling; data arrives within 1–2 seconds.

---

## License

MIT License. Free for educational and commercial use.
