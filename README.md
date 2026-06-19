# Parking Monitor

> Real-time parking lot occupancy from a single RTSP camera, powered by
> YOLOv26 and Bird's Eye View perspective correction.
> Works on **unstructured lots** without painted lane markings.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Docker ready](https://img.shields.io/badge/docker-ready-blue.svg)](Dockerfile)

<!-- Add a real screenshot here once available, e.g.:
![Dashboard](docs/images/dashboard.png)
-->


---

## Getting started

Every parking lot is different — the camera angle, the layout, and which
areas count as parking all change from one site to the next. So before you
run the server you calibrate the system **once** for your camera with the
[Parking Configurator](parking_configurator/README.md), then drop the
result into the project. Follow the steps in order.

### Step 1 — Clone the repository

```bash
git clone https://github.com/USER/parking-monitor.git
```

### Step 2 — Calibrate your camera with the Parking Configurator

The configurator is a local, browser-based setup tool. It connects to your
RTSP camera, walks you through Bird's Eye View calibration and mask
painting, and exports a `parking_config.zip` containing a `.env` file and
the `assets/` your camera needs.

```bash
cd parking_configurator
pip install -e .
python -m parking_configurator        # opens http://127.0.0.1:8765
```

Work through the four steps in the browser (camera → BEV → masks → export)
and download `parking_config.zip`. Full walkthrough:
[`parking_configurator/README.md`](parking_configurator/README.md).

### Step 3 — Apply the configuration to the project

From the project root, unpack the bundle so `.env` and the calibrated
`assets/*.png` land in the right places. The helper script does this for
you and merges the `.env` keys:

```bash
cd ..                                              # back to project root
python scripts/apply_config.py path/to/parking_config.zip
```

Add `--dry-run` first to preview the changes. Prefer to do it by hand?
Unzip `parking_config.zip` into the project root — `.env` goes to the root
and the masks go into `assets/`:

```
parking_config.zip
├── .env                         → project root (CAMERA_URL, SRC_POINTS, BEV size)
└── assets/
    ├── parking_mask.png         → assets/parking_mask.png
    ├── orientation_zones.png    → assets/orientation_zones.png
    └── parking_map.svg          → assets/parking_map.svg (optional, for the UI)
```

> No configurator yet, just trying it out? Copy the template instead:
> `cp .env.example .env`, then edit `.env` and set `CAMERA_URL`. You'll
> get detections, but free-spot accuracy depends on calibrated masks.

### Step 4 — Run the server

```bash
docker compose up
```

Then open <http://localhost:8000/web/> — a live host-status dashboard
(CPU / RAM / disk + pipeline & camera health) polled every two seconds.
Occupancy snapshots are served as JSON at `/api/v1/state`, with a history
endpoint at `/api/v1/history` (1 h / 24 h / 7 d / 30 d).

No Docker? Run directly with uvicorn:

```bash
pip install -r requirements.txt -r api/requirements.txt
uvicorn api.server:app --host 0.0.0.0 --port 8000
```

The SQLite history file lands in `./data/parking_history.db` by default
(override with `DB_PATH=...` if you want it elsewhere).

See [`docs/deployment.md`](docs/deployment.md) for production setups,
reverse-proxy / HTTPS, and Raspberry Pi notes.

---

## Features

- **Unstructured parking** — works without lane markings or painted bays.
- **Perspective correction** — Bird's Eye View transformation from an
  angled wall-mounted camera.
- **Custom parking masks** — supports complex shapes: flowerbeds, exits,
  irregular boundaries.
- **Orientation zones** — parallel and perpendicular spot detection.
- **Real-time monitoring** — RTSP camera support with automatic reconnect.
- **Temporal smoothing** — K-of-N hysteresis with carry-over hides
  single-frame YOLO misses ([details](docs/temporal-smoothing.md)).
- **JSON HTTP API** — FastAPI server exposes live state and occupancy
  history.
- **Occupancy history** — SQLite database, configurable retention,
  survives Docker redeploys via a bind-mount.
- **Built-in web UI** — host-status dashboard (CPU / RAM / disk +
  pipeline and camera health banner).

### Built with

YOLOv26 · OpenCV · FastAPI + uvicorn · Pydantic · NumPy · SQLite

---

## Project structure

```
parking-monitor/
├── monitor.py              # Standalone real-time monitor (OpenCV window)
├── config.py               # Pipeline configuration (BEV points, car size, …)
├── docker-compose.yml      # One-command deployment
├── Dockerfile              # python:3.11-slim + OpenCV system deps
├── requirements.txt        # Backend dependencies
├── .env.example            # Template — copy to .env, set CAMERA_URL
│
├── parking/                # Core detection pipeline
│   ├── detector.py         #   YOLO wrapper + dedupe
│   ├── tracker.py          #   K-of-N temporal hysteresis
│   ├── transformer.py      #   homography → BEV
│   ├── analyzer.py         #   occupancy + free-spot grid scan
│   ├── pipeline.py         #   orchestrator
│   └── models.py           #   Pydantic data models
│
├── api/                    # HTTP server
│   ├── server.py           #   FastAPI app + lifespan
│   ├── settings.py         #   env-var parsing
│   ├── state_store.py      #   thread-safe shared state
│   ├── pipeline_worker.py  #   background worker thread
│   ├── routes/             #   one file per endpoint
│   ├── database.py         #   SQLite history (WAL)
│   └── system_stats.py     #   host CPU/RAM/disk metrics
│
├── web/                    # Browser dashboard (served at /web/)
├── assets/                 # Parking mask + orientation zones (PNGs)
└── docs/                   # Full documentation (see below)
```

Setting up your own camera location? See
[`parking_configurator/`](parking_configurator/README.md) — a local web
tool that walks you through camera connection, BEV calibration, mask
painting and exports a ready-to-use `parking_config.zip`.

`tools/` contains additional CLI calibration utilities (owner use).

---

## Running

| Mode | Command | When to use |
|---|---|---|
| 📊 **Web dashboard + JSON API** | `docker compose up` | Production / sharing with others |
| 🖥️ **Standalone OpenCV monitor** | `python monitor.py` | Local debugging on the machine itself |
| 🛠️ **Setup for a new camera** | `python -m parking_configurator` (from `parking_configurator/`) | Calibrating BEV, painting masks, drawing the map |

Standalone monitor controls: <kbd>q</kbd> quit, <kbd>s</kbd> save
screenshot to `output/`.

For first-time setup on a fresh parking lot, see
[`parking_configurator/README.md`](parking_configurator/README.md).

---

## Documentation

| Page | What's inside |
|---|---|
| [Architecture](docs/architecture.md) | Pipeline diagram, activity-driven model, heartbeat snapshots, DB schema |
| [Configuration reference](docs/configuration.md) | Every `.env` variable and every `config.py` setting |
| [Deployment guide](docs/deployment.md) | Docker, Docker Compose, plain uvicorn, Jenkins, reverse proxy, Raspberry Pi |
| [Temporal smoothing](docs/temporal-smoothing.md) | The K-of-N algorithm and how to tune it |
| [Setup tool](parking_configurator/README.md) | How to set up the camera + masks for your own lot |
| [API specification](api/README.md) | All endpoints, schemas, query parameters, error responses |

---

## Troubleshooting

| Problem | Try |
|---|---|
| **Camera does not connect** | Check `CAMERA_URL` in `.env`. Run `python tools/test_connection.py` to validate the RTSP URL outside of the app. |
| **API returns 503 on first request** | Normal — pipeline is starting. Keep polling, fresh data within ~2 s. |
| **Cars: count flickers** | Already on by default. If still flickering, see [temporal-smoothing.md](docs/temporal-smoothing.md#picking-k-and-n) for tuning. |
| **YOLO misses cars** | Lower `CONF_THRESHOLD` in `config.py` (e.g. `0.35` → `0.25`). |
| **BEV looks distorted** | Recalibrate `SRC_POINTS` — use [`parking_configurator/`](parking_configurator/README.md). |
| **Algorithm marks flowerbeds as free spots** | Paint those areas black in `assets/parking_mask.png` (use the configurator or `tools/edit_parking_mask.py`). |

---

## License

MIT — see [LICENSE](LICENSE). Free for educational and commercial use.

## Contributing

PRs welcome. The detection pipeline (`parking/`) and HTTP layer (`api/`)
are designed to be independently testable — feel free to extend either
without touching the other. Open an issue first for larger changes so we
can agree on the approach.
