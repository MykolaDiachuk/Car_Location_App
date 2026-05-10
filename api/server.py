"""FastAPI server — exposes ParkingState over HTTP.

Run from project root:
    uvicorn api.server:app --host 0.0.0.0 --port 8000

Environment variables (all optional):
    CAMERA_URL          — RTSP URL (overrides config.py default)
    MOCK_MODE           — "true" to skip camera/YOLO (for UI testing)
    CORS_ORIGINS        — comma-separated origins, or "*" (default: "*")
    ANALYSIS_INTERVAL   — seconds between pipeline runs while active (default: 1.0)
    IDLE_TIMEOUT        — seconds of no requests before pipeline pauses (default: 30.0)
    STALE_THRESHOLD     — snapshot age in seconds before `stale=true` (default: 10.0)
    DB_PATH             — SQLite file path (default: /data/parking_history.db)
    RECORD_INTERVAL     — seconds between DB writes while active (default: 120.0)
    RETENTION_DAYS      — auto-delete snapshots older than N days (default: 90)
    HEARTBEAT_INTERVAL  — seconds between background snapshots while idle
                          (default: 3600.0 = 1 h). Set to 0 to disable.

Activity-based pipeline:
    The pipeline only processes frames continuously while at least one
    client has polled /api/v1/state recently (within IDLE_TIMEOUT). When
    idle, the camera is released.

    To keep statistics flowing and to guarantee that the next visitor
    sees data no older than HEARTBEAT_INTERVAL, the worker still wakes
    up periodically while idle, grabs ONE frame, writes it to the DB,
    and goes back to sleep. This costs a few seconds of camera time per
    hour by default.
"""
import logging
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

# Force RTSP over TCP with 5-second connect/read timeout. Without this OpenCV's
# default FFmpeg backend can block indefinitely on an unreachable camera.
# Must be set BEFORE `import cv2`.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|stimeout;5000000",
)

import cv2
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from parking.models import (
    CameraHealth,
    HealthResponse,
    HistoryResponse,
    ParkingState,
    PipelineHealth,
    PipelineStatus,
    StateResponse,
)
from api.database import (
    cleanup_old_data,
    get_snapshot_count,
    init_db,
    query_history,
    record_snapshot,
)
from api.system_stats import collector as _sys_collector

# ── Configuration (env-driven) ────────────────────────────────────────────────


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _env_origins(name: str, default: str = "*") -> list[str]:
    raw = os.getenv(name, default).strip()
    if raw == "*" or not raw:
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


MOCK_MODE = _env_bool("MOCK_MODE", False)
ANALYSIS_INTERVAL = _env_float("ANALYSIS_INTERVAL", 1.0)
IDLE_TIMEOUT = _env_float("IDLE_TIMEOUT", 30.0)
STALE_THRESHOLD = _env_float("STALE_THRESHOLD", 10.0)
CORS_ORIGINS = _env_origins("CORS_ORIGINS")
DB_PATH = os.getenv("DB_PATH", "/data/parking_history.db")
RECORD_INTERVAL = _env_float("RECORD_INTERVAL", 120.0) #Sec
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "90"))
HEARTBEAT_INTERVAL = _env_float("HEARTBEAT_INTERVAL", 3600.0)  # 1 hour; 0 disables

RECONNECT_BACKOFF_INITIAL = 1.0
RECONNECT_BACKOFF_MAX = 30.0
HEARTBEAT_WARMUP_FRAMES = 3  # discard buffered frames after RTSP reconnect

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Shared state ──────────────────────────────────────────────────────────────

_state_lock = threading.Lock()
_latest_state: Optional[ParkingState] = None
_latest_state_at: float = 0.0  # time.monotonic() when state was set

_activity_lock = threading.Lock()
_last_activity_at: float = 0.0
_wake_event = threading.Event()
_shutdown_event = threading.Event()

_pipeline_status: PipelineStatus = "starting"
_camera_connected: bool = False
_frames_processed: int = 0
_pipeline_errors: int = 0
_last_error: Optional[str] = None
_started_at: float = time.monotonic()


_last_record_at: float = 0.0
_last_heartbeat_at: float = 0.0


def _set_state(state: ParkingState, force_record: bool = False) -> None:
    """Update the cached snapshot and (optionally) persist to DB.

    Active loop calls with force_record=False — DB write is throttled by
    RECORD_INTERVAL. The idle-time heartbeat path passes force_record=True
    so the row always lands, regardless of throttle.
    """
    global _latest_state, _latest_state_at, _frames_processed, _last_record_at
    with _state_lock:
        _latest_state = state
        _latest_state_at = time.monotonic()
        _frames_processed += 1

    now = time.monotonic()
    if force_record or now - _last_record_at >= RECORD_INTERVAL:
        _last_record_at = now
        try:
            record_snapshot(state)
        except Exception as exc:
            logger.warning("Failed to record snapshot to DB: %s", exc)


def _get_state() -> tuple[Optional[ParkingState], float]:
    with _state_lock:
        return _latest_state, _latest_state_at


def _mark_activity() -> None:
    """Record that a client just polled — keeps the pipeline awake."""
    global _last_activity_at
    with _activity_lock:
        _last_activity_at = time.monotonic()
    _wake_event.set()


def _is_active(now: float) -> bool:
    with _activity_lock:
        return (now - _last_activity_at) < IDLE_TIMEOUT


# ── Background worker ─────────────────────────────────────────────────────────


def _release_camera(cap: Optional[cv2.VideoCapture]) -> None:
    global _camera_connected
    if cap is not None:
        try:
            cap.release()
        except Exception:
            pass
    _camera_connected = False


def _connect_camera(url: str) -> Optional[cv2.VideoCapture]:
    global _camera_connected
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        try:
            cap.release()
        except Exception:
            pass
        _camera_connected = False
        return None
    _camera_connected = True
    return cap


def _record_error(exc: BaseException) -> None:
    global _pipeline_errors, _last_error
    _pipeline_errors += 1
    _last_error = f"{type(exc).__name__}: {exc}"


def _take_heartbeat_snapshot(pipeline, camera_url: str) -> bool:
    """Idle-time heartbeat: connect, grab one frame, process, force-record, release.

    Used when no clients are online but we still want a snapshot every
    HEARTBEAT_INTERVAL seconds so the history DB stays continuous and the
    next visitor sees fresh-ish data immediately.
    """
    cap = _connect_camera(camera_url)
    if cap is None:
        return False
    try:
        # Discard buffered frames — RTSP often returns stale data right
        # after reconnect.
        for _ in range(max(0, HEARTBEAT_WARMUP_FRAMES - 1)):
            cap.read()
        ret, frame = cap.read()
        if not ret or frame is None:
            return False
        result = pipeline.process_frame(frame)
        _set_state(result.state, force_record=True)
        return True
    finally:
        _release_camera(cap)


def _pipeline_worker() -> None:
    """Activity-driven pipeline loop with idle-time heartbeats.

    States:
      idle     — no recent requests; sleep until woken by a poll OR until
                 HEARTBEAT_INTERVAL elapses (then take one background
                 snapshot and go back to sleep).
      starting — woken up, attempting to (re)connect to camera.
      running  — processing frames at ANALYSIS_INTERVAL.
      error    — connection or processing failure; backoff and retry while active.
    """
    global _pipeline_status, _last_heartbeat_at

    from config import ParkingConfig
    from parking.pipeline import ParkingPipeline

    config = ParkingConfig()
    if not config.CAMERA_URL:
        logger.error(
            "CAMERA_URL is not set. Add it to .env or start with MOCK_MODE=true."
        )
        _pipeline_status = "error"
        _record_error(RuntimeError("CAMERA_URL is empty — set it in .env"))
        return

    try:
        pipeline = ParkingPipeline(config)
    except Exception as exc:
        logger.exception("Failed to initialize pipeline")
        _pipeline_status = "error"
        _record_error(exc)
        return

    cap: Optional[cv2.VideoCapture] = None
    backoff = RECONNECT_BACKOFF_INITIAL

    # Start the heartbeat clock at server boot so the first heartbeat fires
    # HEARTBEAT_INTERVAL seconds later (not immediately).
    _last_heartbeat_at = time.monotonic()

    while not _shutdown_event.is_set():
        now = time.monotonic()

        if not _is_active(now):
            # Hold no resources while idle.
            if cap is not None:
                logger.info("Pipeline going idle — releasing camera")
                _release_camera(cap)
                cap = None

            # Heartbeat due?
            elapsed = now - _last_heartbeat_at
            if HEARTBEAT_INTERVAL > 0 and elapsed >= HEARTBEAT_INTERVAL:
                _pipeline_status = "starting"
                logger.info("Heartbeat — taking idle background snapshot")
                ok = _take_heartbeat_snapshot(pipeline, config.CAMERA_URL)
                _last_heartbeat_at = time.monotonic()
                if ok:
                    logger.info("Heartbeat snapshot recorded")
                    _pipeline_status = "idle"
                else:
                    msg = f"Heartbeat failed: camera unreachable ({_redact_url(config.CAMERA_URL)})"
                    logger.warning(msg)
                    _record_error(RuntimeError(msg))
                    _pipeline_status = "error"
                continue

            _pipeline_status = "idle" if _pipeline_status != "error" else _pipeline_status
            # Sleep until next heartbeat or wake event. Cap at 60 s so
            # shutdown/heartbeat re-check stays responsive.
            if HEARTBEAT_INTERVAL > 0:
                until_heartbeat = max(1.0, HEARTBEAT_INTERVAL - elapsed)
                wait_s = min(until_heartbeat, 60.0)
            else:
                wait_s = 5.0
            _wake_event.wait(timeout=wait_s)
            _wake_event.clear()
            continue

        if cap is None:
            _pipeline_status = "starting"
            logger.info("Activity detected — connecting to camera")
            cap = _connect_camera(config.CAMERA_URL)
            if cap is None:
                _pipeline_status = "error"
                _last_error_msg = f"Camera unreachable: {_redact_url(config.CAMERA_URL)}"
                logger.warning(f"{_last_error_msg} — retrying in {backoff:.0f}s")
                _record_error(RuntimeError(_last_error_msg))
                if _shutdown_event.wait(timeout=backoff):
                    break
                backoff = min(backoff * 2, RECONNECT_BACKOFF_MAX)
                continue
            backoff = RECONNECT_BACKOFF_INITIAL
            logger.info("Camera connected")

        ret, frame = cap.read()
        if not ret:
            logger.warning("Frame read failed — reconnecting")
            _release_camera(cap)
            cap = None
            continue

        try:
            result = pipeline.process_frame(frame)
            _set_state(result.state)
            _pipeline_status = "running"
            # Active processing keeps DB fresh too — reset heartbeat clock so
            # we don't double-snapshot right after clients leave.
            _last_heartbeat_at = time.monotonic()
        except Exception as exc:
            logger.exception("Pipeline error")
            _record_error(exc)
            _pipeline_status = "error"

        if _shutdown_event.wait(timeout=ANALYSIS_INTERVAL):
            break

    _release_camera(cap)
    logger.info("Pipeline worker stopped")


def _redact_url(url: str) -> str:
    """Strip credentials from RTSP URL for logging/health output."""
    if "@" not in url:
        return url
    scheme, rest = url.split("://", 1) if "://" in url else ("", url)
    _, host_part = rest.split("@", 1)
    return f"{scheme}://{host_part}" if scheme else host_part


def _mock_worker() -> None:
    """Mock variant of the pipeline worker — same activity gating + heartbeat."""
    global _pipeline_status, _last_heartbeat_at
    from api.mock_state import build_mock_state

    tick = 0
    _last_heartbeat_at = time.monotonic()

    while not _shutdown_event.is_set():
        now = time.monotonic()

        if not _is_active(now):
            elapsed = now - _last_heartbeat_at
            if HEARTBEAT_INTERVAL > 0 and elapsed >= HEARTBEAT_INTERVAL:
                logger.info("Heartbeat (mock) — recording idle snapshot")
                try:
                    _set_state(build_mock_state(tick), force_record=True)
                    tick += 1
                    _pipeline_status = "idle"
                except Exception as exc:
                    _record_error(exc)
                    _pipeline_status = "error"
                _last_heartbeat_at = time.monotonic()
                continue

            _pipeline_status = "idle"
            if HEARTBEAT_INTERVAL > 0:
                until_heartbeat = max(1.0, HEARTBEAT_INTERVAL - elapsed)
                wait_s = min(until_heartbeat, 60.0)
            else:
                wait_s = 5.0
            _wake_event.wait(timeout=wait_s)
            _wake_event.clear()
            continue

        _pipeline_status = "running"
        try:
            _set_state(build_mock_state(tick))
            tick += 1
            _last_heartbeat_at = time.monotonic()
        except Exception as exc:
            _record_error(exc)
            _pipeline_status = "error"

        if _shutdown_event.wait(timeout=ANALYSIS_INTERVAL):
            break


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Database ──
    init_db(DB_PATH)
    deleted = cleanup_old_data(RETENTION_DAYS)
    if deleted:
        logger.info("Startup cleanup: removed %d old snapshots", deleted)
    logger.info(
        "DB: path=%s  record_interval=%ss  retention=%sd  rows=%d",
        DB_PATH, RECORD_INTERVAL, RETENTION_DAYS, get_snapshot_count(),
    )

    # ── Pipeline worker ──
    target = _mock_worker if MOCK_MODE else _pipeline_worker
    if MOCK_MODE:
        logger.info("Starting in MOCK MODE — no camera or YOLO")
    hb = f"{HEARTBEAT_INTERVAL}s" if HEARTBEAT_INTERVAL > 0 else "disabled"
    logger.info(
        f"Pipeline config: interval={ANALYSIS_INTERVAL}s "
        f"idle_timeout={IDLE_TIMEOUT}s stale_threshold={STALE_THRESHOLD}s "
        f"heartbeat={hb}"
    )

    t = threading.Thread(target=target, daemon=True, name="pipeline-worker")
    t.start()
    try:
        yield
    finally:
        logger.info("Shutting down pipeline worker")
        _shutdown_event.set()
        _wake_event.set()
        t.join(timeout=5.0)


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Parking Monitor API",
    version="1.0.0",
    description="Real-time parking lot occupancy. Poll /api/v1/state to read.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
    max_age=3600,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _bev_dimensions() -> tuple[int, int]:
    from config import ParkingConfig
    return ParkingConfig.BEV_WIDTH, ParkingConfig.BEV_HEIGHT


def _build_state_response(
    state: ParkingState,
    snapshot_at_mono: float,
) -> StateResponse:
    bev_w, bev_h = _bev_dimensions()
    age = max(0.0, time.monotonic() - snapshot_at_mono)
    return StateResponse(
        timestamp=state.timestamp,
        age_seconds=round(age, 2),
        stale=age > STALE_THRESHOLD,
        pipeline_status=_pipeline_status,
        bev_width=bev_w,
        bev_height=bev_h,
        total_spots=state.total_spots,
        occupied=state.occupied,
        free=state.free,
        occupancy_percent=state.occupancy_percent,
        spots=state.spots,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@app.get("/api/v1/state", response_model=StateResponse)
def get_state() -> StateResponse:
    """Latest parking snapshot.

    Marks the client as active — this keeps the pipeline running.
    Returns 503 only on cold start (no snapshot yet); after that, always
    returns the latest cached state with `stale` and `age_seconds` so the
    frontend can decide how to render staleness.
    """
    _mark_activity()
    state, snapshot_at = _get_state()
    if state is None:
        raise HTTPException(
            status_code=503,
            detail="Pipeline starting — no snapshot yet. Retry shortly.",
        )
    return _build_state_response(state, snapshot_at)


@app.get("/api/v1/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Operational health — does not mark activity (safe to poll from monitoring)."""
    bev_w, bev_h = _bev_dimensions()

    if _pipeline_status == "error":
        overall = "error"
    elif _latest_state is None:
        overall = "starting"
    else:
        overall = "ok"

    last_frame_at: datetime | None = None
    state, _ = _get_state()
    if state is not None:
        last_frame_at = state.timestamp

    return HealthResponse(
        status=overall,
        uptime_seconds=round(time.monotonic() - _started_at, 1),
        pipeline=PipelineHealth(
            status=_pipeline_status,
            frames_processed=_frames_processed,
            errors=_pipeline_errors,
            last_error=_last_error,
        ),
        camera=CameraHealth(
            connected=_camera_connected,
            last_frame_at=last_frame_at,
        ),
        bev_width=bev_w,
        bev_height=bev_h,
    )


_PERIOD_RE = re.compile(r"^(\d+)([hd])$")
_MAX_QUERY_DAYS = 90


def _parse_period(raw: str) -> timedelta:
    m = _PERIOD_RE.match(raw.strip().lower())
    if not m:
        raise ValueError(f"Invalid period '{raw}'. Use <number>h or <number>d, e.g. 24h, 7d.")
    value, unit = int(m.group(1)), m.group(2)
    if unit == "h":
        return timedelta(hours=value)
    return timedelta(days=value)


@app.get("/api/v1/history", response_model=HistoryResponse)
def get_history(
    period: str | None = Query(
        None,
        description="Lookback window, e.g. 1h, 6h, 24h, 7d, 30d. "
                    "Mutually exclusive with from/to.",
        examples=["1h", "6h", "24h", "7d", "30d"],
    ),
    from_dt: datetime | None = Query(
        None,
        alias="from",
        description="Start of time range (ISO 8601 UTC).",
    ),
    to_dt: datetime | None = Query(
        None,
        alias="to",
        description="End of time range (ISO 8601 UTC). Defaults to now.",
    ),
) -> HistoryResponse:
    """Historical occupancy data for chart rendering.

    Provide either ``period`` **or** ``from``/``to``. When using ``period``
    the window is ``[now - period, now)``.

    Aggregation granularity is chosen automatically based on the time span
    so that the response contains ~120-360 data points.
    """
    from parking.models import HistoryPoint

    now = datetime.now(timezone.utc)

    # ── resolve time range ──
    if period and from_dt:
        raise HTTPException(400, "Provide either 'period' or 'from'/'to', not both.")

    if period:
        try:
            delta = _parse_period(period)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        qto = now
        qfrom = now - delta
    elif from_dt:
        qfrom = from_dt if from_dt.tzinfo else from_dt.replace(tzinfo=timezone.utc)
        qto = (
            (to_dt if to_dt.tzinfo else to_dt.replace(tzinfo=timezone.utc))
            if to_dt
            else now
        )
    else:
        # Default: last 24 hours
        qto = now
        qfrom = now - timedelta(hours=24)

    # ── validate ──
    if qfrom >= qto:
        raise HTTPException(400, "'from' must be before 'to'.")
    if (qto - qfrom).days > _MAX_QUERY_DAYS:
        raise HTTPException(400, f"Maximum query range is {_MAX_QUERY_DAYS} days.")

    # ── query ──
    rows, bucket = query_history(qfrom, qto)
    points = [
        HistoryPoint(
            # DB stores naive UTC strings — tag with timezone so JSON output
            # includes 'Z' and the frontend parses them correctly.
            timestamp=datetime.strptime(r["timestamp"], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            ),
            total_spots=int(r["total_spots"]),
            occupied=int(r["occupied"]),
            free=int(r["free"]),
            occupancy_percent=float(r["occupancy_percent"]),
        )
        for r in rows
    ]

    return HistoryResponse(
        period_from=qfrom,
        period_to=qto,
        bucket_seconds=bucket,
        point_count=len(points),
        points=points,
    )


@app.get("/api/v1/system")
def get_system_stats() -> dict:
    """Current system resource metrics + server info + history."""
    current = _sys_collector.collect()
    return {
        "server": _sys_collector.get_server_info(),
        "current": current,
        "history": _sys_collector.get_history(),
    }


@app.get("/")
def root() -> dict:
    """API index — points clients at the docs and main endpoint."""
    return {
        "name": "Parking Monitor API",
        "version": "1.0.0",
        "endpoints": {
            "state": "/api/v1/state",
            "health": "/api/v1/health",
            "history": "/api/v1/history",
            "docs": "/docs",
            "ui": "/web/",
        },
    }


# ── Static files (must be mounted last — API routes above take priority) ──────
from starlette.staticfiles import StaticFiles as _StaticFiles

app.mount("/assets", _StaticFiles(directory="assets"), name="assets")
app.mount("/web", _StaticFiles(directory="web", html=True), name="web")
