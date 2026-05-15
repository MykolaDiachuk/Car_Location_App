# Configuration reference

All tunable values live in two places:

- **`.env` file** — runtime / deployment options consumed by the HTTP server.
  Parsed once at startup by [`api/settings.py`](../api/settings.py).
- **`config.py`** — physical setup of the parking lot and detection
  algorithm. Rarely changes after the initial calibration.

This page is the single source of truth for both — other docs link here
instead of duplicating tables.

---

## Environment variables (`.env`)

Copy `.env.example` to `.env` and edit before first run.

### Required

| Variable | Description |
|---|---|
| `CAMERA_URL` | RTSP stream URL, e.g. `rtsp://user:pass@192.168.0.10:554/stream`. The server refuses to start without it. |

### Optional — pipeline behaviour

| Variable | Default | Description |
|---|---|---|
| `ANALYSIS_INTERVAL` | `1.0` | Seconds between pipeline runs while active. |
| `IDLE_TIMEOUT` | `30.0` | Seconds of no `/state` polls before the camera is released. |
| `STALE_THRESHOLD` | `10.0` | Snapshots older than this are marked `stale=true` in `/state` responses. |
| `HEARTBEAT_INTERVAL` | `3600.0` | Seconds between idle-time background snapshots. The worker briefly wakes the camera, grabs one frame, writes to DB, and sleeps again. Keeps history continuous and guarantees the next visitor sees data no older than this. Set to `0` to disable. |

### Optional — storage

| Variable | Default | Description |
|---|---|---|
| `DB_PATH` | `/data/parking_history.db` | SQLite history database file path. Use a bind-mount in Docker so it survives redeploys. |
| `RECORD_INTERVAL` | `120.0` | Minimum seconds between DB writes while active (throttle). |
| `RETENTION_DAYS` | `90` | Snapshots older than this are deleted on startup. |

### Optional — HTTP

| Variable | Default | Description |
|---|---|---|
| `CORS_ORIGINS` | `*` | Comma-separated list of allowed origins, or `*`. Only `GET` is exposed. |

### Optional — temporal smoothing (K-of-N hysteresis)

See [temporal-smoothing.md](temporal-smoothing.md) for the algorithm.

| Variable | Default | Description |
|---|---|---|
| `TEMPORAL_SMOOTH_ENABLED` | `true` | Enable K-of-N temporal hysteresis with carry-over. Set to `false` to disable. |
| `TEMPORAL_WINDOW_N` | `5` | Rolling window size in frames. |
| `TEMPORAL_MIN_K` | `3` | Minimum frames a bbox must appear in to survive. |
| `TEMPORAL_IOU_MATCH` | `0.3` | IoU threshold for matching bboxes across frames. |
| `TEMPORAL_MAX_AGE_SECONDS` | `10.0` | History entries older than this are dropped before filtering. Should be `≥ TEMPORAL_WINDOW_N × ANALYSIS_INTERVAL × 1.5`. |

---

## Pipeline configuration (`config.py`)

These values describe the **physical setup** of one specific camera and
parking lot. After initial calibration they only change if you move the
camera or repaint the lot.

| Setting | Default | Description |
|---|---|---|
| `SRC_POINTS` | _(calibrated)_ | 4 camera-space points defining the BEV quad (TL → TR → BR → BL). Edit with `tools/find_bev_points.py` or the Configurator. |
| `BEV_WIDTH` | `1200` | BEV canvas width in pixels. |
| `BEV_HEIGHT` | `800` | BEV canvas height in pixels. |
| `CAR_WIDTH` | `150` | Car footprint width in BEV pixels (constant — no depth correction). |
| `CAR_HEIGHT` | `80` | Car footprint height in BEV pixels. |
| `CHECK_STEP` | `20` | Grid scan stride for free-spot detection (pixels). |
| `DETECTION_ANCHOR` | `"bottom_right"` | Where on the YOLO bbox to anchor the BEV spot: `"bottom_center"` or `"bottom_right"`. |
| `MODEL_PATH` | `yolo26m.pt` | YOLO weights file. |
| `MASK_PATH` | `assets/parking_mask.png` | White = parking allowed, black = forbidden. |
| `ZONE_MASK_PATH` | `assets/orientation_zones.png` | Green = parallel, blue = perpendicular. |
| `VEHICLE_CLASSES` | `[2, 3, 5, 7]` | COCO class IDs: car, motorcycle, bus, truck. |
| `CONF_THRESHOLD` | `0.35` | Minimum YOLO detection confidence. Lower → more recall, more false positives. |
| `OVERLAP_THRESHOLD` | `0.8` | Post-detection dedupe: drop a smaller bbox if its intersection with a larger one covers at least this fraction of the smaller bbox's area. Catches "two boxes on the same car" that NMS misses. Set to `1.0` to disable. |

See [calibration.md](calibration.md) for how to set `SRC_POINTS` and paint
the mask files for a new camera location.
