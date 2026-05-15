# Parking Monitor

> Real-time parking lot occupancy from a single RTSP camera, powered by
> YOLOv11 and Bird's Eye View perspective correction.
> Works on **unstructured lots** without painted lane markings.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Docker ready](https://img.shields.io/badge/docker-ready-blue.svg)](Dockerfile)

<!-- Add a real screenshot here once available, e.g.:
![Dashboard](docs/images/dashboard.png)
-->


---

## Quick start

```bash
git clone https://github.com/USER/parking-monitor.git
cd parking-monitor
cp .env.example .env       # then edit .env and set CAMERA_URL
docker compose up
```

Open <http://localhost:8000/web/> — the dashboard polls the API every two
seconds and shows live occupancy plus a 1 h / 24 h / 7 d / 30 d history
chart.

No Docker? Run directly with uvicorn:

```bash
pip install -r requirements.txt -r api/requirements.txt
DB_PATH=./parking_history.db uvicorn api.server:app --host 0.0.0.0 --port 8000
```

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
- **Built-in web UI** — dashboard with live spot overlay, time-series
  chart, and host system metrics.

### Built with

YOLOv11 · OpenCV · FastAPI + uvicorn · Pydantic · NumPy · SQLite

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

`tools/` and `parking_configurator/` contain owner-only calibration
utilities — see [`docs/calibration.md`](docs/calibration.md) if you want to
redo them for your own camera.

---

## Running

| Mode | Command | When to use |
|---|---|---|
| 📊 **Web dashboard + JSON API** | `docker compose up` | Production / sharing with others |
| 🖥️ **Standalone OpenCV monitor** | `python monitor.py` | Local debugging on the machine itself |
| 🛠️ **Calibration** | [`docs/calibration.md`](docs/calibration.md) | Setting up a new camera location |

Standalone monitor controls: <kbd>q</kbd> quit, <kbd>s</kbd> save
screenshot to `output/`.

---

## Documentation

| Page | What's inside |
|---|---|
| [Architecture](docs/architecture.md) | Pipeline diagram, activity-driven model, heartbeat snapshots, DB schema |
| [Configuration reference](docs/configuration.md) | Every `.env` variable and every `config.py` setting |
| [Deployment guide](docs/deployment.md) | Docker, Docker Compose, plain uvicorn, Jenkins, reverse proxy, Raspberry Pi |
| [Temporal smoothing](docs/temporal-smoothing.md) | The K-of-N algorithm and how to tune it |
| [Calibration](docs/calibration.md) | How to set up the camera + masks for your own lot |
| [API specification](api/README.md) | All endpoints, schemas, query parameters, error responses |
| [Frontend integration](api/FRONTEND.md) | Polling, coordinates, and tips for building your own UI |

---

## Troubleshooting

| Problem | Try |
|---|---|
| **Camera does not connect** | Check `CAMERA_URL` in `.env`. Run `python tools/test_connection.py` to validate the RTSP URL outside of the app. |
| **API returns 503 on first request** | Normal — pipeline is starting. Keep polling, fresh data within ~2 s. |
| **Cars: count flickers** | Already on by default. If still flickering, see [temporal-smoothing.md](docs/temporal-smoothing.md#picking-k-and-n) for tuning. |
| **YOLO misses cars** | Lower `CONF_THRESHOLD` in `config.py` (e.g. `0.35` → `0.25`). |
| **BEV looks distorted** | Recalibrate `SRC_POINTS` — see [calibration.md](docs/calibration.md). |
| **Algorithm marks flowerbeds as free spots** | Paint those areas black in `assets/parking_mask.png`. |

---

## License

MIT — see [LICENSE](LICENSE). Free for educational and commercial use.

## Contributing

PRs welcome. The detection pipeline (`parking/`) and HTTP layer (`api/`)
are designed to be independently testable — feel free to extend either
without touching the other. Open an issue first for larger changes so we
can agree on the approach.
