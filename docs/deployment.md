# Deployment guide

Three ways to run Parking Monitor in production, from simplest to most
involved.

---

## Option 1 — Docker Compose (recommended)

The simplest path. One file, one command.

```bash
git clone https://github.com/USER/parking-monitor.git
cd parking-monitor
cp .env.example .env       # edit: set CAMERA_URL
docker compose up -d
```

Open `http://localhost:8000/web/`. Logs: `docker compose logs -f`.

The bundled [`docker-compose.yml`](../docker-compose.yml) mounts
`./data/` from the host so the SQLite history database survives container
redeploys.

### What the compose file does

```yaml
services:
  parking-monitor:
    build: .
    ports: ["8000:8000"]
    env_file: .env
    volumes:
      - ./data:/data       # SQLite history persists here
    restart: unless-stopped
```

---

## Option 2 — Plain Docker

If you prefer not to install Docker Compose:

```bash
docker build -t parking-monitor .
docker run -d \
  --name parking-monitor \
  -p 8000:8000 \
  --env-file .env \
  -v $(pwd)/data:/data \
  --restart unless-stopped \
  parking-monitor
```

The [`Dockerfile`](../Dockerfile) uses `python:3.11-slim` and installs the
OpenCV system dependencies (`libgl1`, `libglib2.0-0`).

---

## Option 3 — Bare uvicorn

Useful for local development or when you don't want a container at all.

```bash
pip install -r requirements.txt -r api/requirements.txt
cp .env.example .env       # edit: set CAMERA_URL
uvicorn api.server:app --host 0.0.0.0 --port 8000
```

The SQLite history file lands in `<project_root>/data/parking_history.db`
by default (auto-created on first run). Override with `DB_PATH=...` if you
want it elsewhere. The Docker images explicitly set
`DB_PATH=/data/parking_history.db` so history lands on the persistent
bind-mount.

For development reloads: append `--reload`. Don't use `--reload` in
production — the background pipeline worker doesn't survive auto-reload.

---

## CI / CD with Jenkins

The bundled [`Jenkinsfile`](../Jenkinsfile) implements a minimal
build → stop → run pipeline:

1. `git checkout`
2. `docker build -t parking-monitor .`
3. `docker stop parking-monitor || true && docker rm parking-monitor || true`
4. `docker run -d ...` with `--env-file` and `-v /home/<user>/parking-data:/data`

Adapt the volume path to wherever you want the SQLite file to live on the
host. `docker rm` + `docker run` does NOT touch that directory, so history
survives every redeploy.

---

## Production tips

### Reverse proxy + HTTPS

Run the app on a private port and put nginx / Caddy / Traefik in front for
TLS termination. Example nginx snippet:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Then set `CORS_ORIGINS=https://your-domain.tld` in `.env` instead of `*`.

### Resource limits

YOLOv11 inference is the dominant CPU cost. A `yolo26m.pt` model at
1 frame/second runs comfortably on:

- **Raspberry Pi 4 (4 GB)** — ~1.5 s/frame, set `ANALYSIS_INTERVAL=2.0`
- **Any x86 with 4 cores** — well under 1 s/frame at 1.0 s interval
- **GPU** — overkill for this workload; the bottleneck is RTSP, not inference

If memory matters, `python:3.11-slim` + the wheel of `ultralytics` ends up
around 700 MB in RAM during inference. Set Docker's `--memory=1g` to bound
worst-case usage.

### Raspberry Pi specifics

The reference deployment runs on a Pi 4 (4 GB) with:

- Host path `/home/mykola/parking-data/` bind-mounted to `/data`
- `RECORD_INTERVAL=120` (one snapshot every 2 min while active)
- `HEARTBEAT_INTERVAL=3600` (one extra snapshot per hour while idle)
- `ANALYSIS_INTERVAL=2.0` to keep CPU below 70 %

Watch the CPU temperature in the dashboard's system panel — Pi 4 throttles
above 80 °C.

### Monitoring

`/api/v1/health` is the operational health endpoint. It does NOT mark
client activity, so external uptime monitors (UptimeRobot, Healthchecks,
…) can poll it without keeping the pipeline awake.

The dashboard's system panel reads `/api/v1/system` every 2 s for live
CPU / RAM / disk / network metrics.
