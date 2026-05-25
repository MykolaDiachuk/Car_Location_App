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

Activity-based pipeline:
    The pipeline only processes frames while at least one client has polled
    /api/v1/state recently (within IDLE_TIMEOUT). When idle, the camera is
    released. The first poll after idle wakes the worker; the response
    returns the last cached snapshot immediately, and fresh data is
    available on the next poll a few seconds later.
"""
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import cv2
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from parking.models import (
    CameraHealth,
    HealthResponse,
    ParkingState,
    PipelineHealth,
    PipelineStatus,
    StateResponse,
)

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

RECONNECT_BACKOFF_INITIAL = 1.0
RECONNECT_BACKOFF_MAX = 30.0

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


def _set_state(state: ParkingState) -> None:
    global _latest_state, _latest_state_at, _frames_processed
    with _state_lock:
        _latest_state = state
        _latest_state_at = time.monotonic()
        _frames_processed += 1


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


def _pipeline_worker() -> None:
    """Activity-driven pipeline loop.

    States:
      idle     — no recent requests; sleep until woken by a poll.
      starting — woken up, attempting to (re)connect to camera.
      running  — processing frames at ANALYSIS_INTERVAL.
      error    — connection or processing failure; backoff and retry while active.
    """
    global _pipeline_status

    from config import ParkingConfig
    from parking.pipeline import ParkingPipeline

    config = ParkingConfig()
    try:
        pipeline = ParkingPipeline(config)
    except Exception as exc:
        logger.exception("Failed to initialize pipeline")
        _pipeline_status = "error"
        _record_error(exc)
        return

    cap: Optional[cv2.VideoCapture] = None
    backoff = RECONNECT_BACKOFF_INITIAL

    while not _shutdown_event.is_set():
        now = time.monotonic()

        if not _is_active(now):
            if cap is not None:
                logger.info("Pipeline going idle — releasing camera")
                _release_camera(cap)
                cap = None
            _pipeline_status = "idle"
            # Wake immediately when a request arrives, otherwise re-check periodically.
            _wake_event.wait(timeout=5.0)
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
    """Mock variant of the pipeline worker — same activity gating."""
    global _pipeline_status
    from api.mock_state import build_mock_state

    tick = 0
    while not _shutdown_event.is_set():
        now = time.monotonic()
        if not _is_active(now):
            _pipeline_status = "idle"
            _wake_event.wait(timeout=5.0)
            _wake_event.clear()
            continue

        _pipeline_status = "running"
        try:
            _set_state(build_mock_state(tick))
            tick += 1
        except Exception as exc:
            _record_error(exc)
            _pipeline_status = "error"

        if _shutdown_event.wait(timeout=ANALYSIS_INTERVAL):
            break


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    target = _mock_worker if MOCK_MODE else _pipeline_worker
    if MOCK_MODE:
        logger.info("Starting in MOCK MODE — no camera or YOLO")
    logger.info(
        f"Pipeline config: interval={ANALYSIS_INTERVAL}s "
        f"idle_timeout={IDLE_TIMEOUT}s stale_threshold={STALE_THRESHOLD}s"
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


@app.get("/")
def root() -> dict:
    """API index — points clients at the docs and main endpoint."""
    return {
        "name": "Parking Monitor API",
        "version": "1.0.0",
        "endpoints": {
            "state": "/api/v1/state",
            "health": "/api/v1/health",
            "docs": "/docs",
        },
    }
