"""FastAPI application — entry point for the Parking Monitor HTTP API.

Run from the project root::

    uvicorn api.server:app --host 0.0.0.0 --port 8000

The pipeline is **activity-driven**: it processes frames continuously only
while at least one client has polled ``/api/v1/state`` recently. When idle,
the camera is released. A periodic heartbeat snapshot keeps the history DB
continuous so a returning visitor sees recent data immediately.

For configuration details (env vars, defaults) see ``docs/configuration.md``.
For endpoint contracts see ``api/README.md``.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

# Force RTSP over TCP with a 5-second connect/read timeout. Without this
# OpenCV's default FFmpeg backend can block indefinitely on an unreachable
# camera. Must be set BEFORE ``import cv2`` anywhere in the process.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|stimeout;5000000",
)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from config import ParkingConfig
from parking.pipeline import ParkingPipeline
from api.database import cleanup_old_data, get_snapshot_count, init_db
from api.pipeline_worker import PipelineWorker
from api.routes import health, history, index, state, system
from api.settings import Settings
from api.state_store import StateStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise database, build the pipeline, and start the worker thread."""
    settings = Settings.from_env()
    config = ParkingConfig()

    # ── Database ────────────────────────────────────────────────────────────
    init_db(settings.db_path)
    deleted = cleanup_old_data(settings.retention_days)
    if deleted:
        logger.info("Startup cleanup: removed %d old snapshots", deleted)
    logger.info(
        "DB: path=%s  record_interval=%ss  retention=%sd  rows=%d",
        settings.db_path,
        settings.record_interval,
        settings.retention_days,
        get_snapshot_count(),
    )

    # ── Pipeline ────────────────────────────────────────────────────────────
    logger.info(
        "Pipeline config: interval=%ss idle_timeout=%ss stale_threshold=%ss heartbeat=%s",
        settings.analysis_interval,
        settings.idle_timeout,
        settings.stale_threshold,
        settings.heartbeat_summary(),
    )

    store = StateStore(record_interval=settings.record_interval)
    worker: PipelineWorker | None = None

    if not config.CAMERA_URL:
        logger.error("CAMERA_URL is not set. Add it to .env.")
        store.set_pipeline_status("error")
        store.record_error(RuntimeError("CAMERA_URL is empty — set it in .env"))
    else:
        try:
            pipeline = ParkingPipeline(config)
        except Exception as exc:
            logger.exception("Failed to initialize pipeline")
            store.set_pipeline_status("error")
            store.record_error(exc)
        else:
            worker = PipelineWorker(
                settings=settings,
                store=store,
                pipeline=pipeline,
                camera_url=config.CAMERA_URL,
            )
            worker.start()

    app.state.settings = settings
    app.state.store = store
    app.state.worker = worker

    try:
        yield
    finally:
        logger.info("Shutting down pipeline worker")
        if worker is not None:
            worker.stop(timeout=5.0)


def _cors_origins_from_env() -> list[str]:
    """Read CORS origins eagerly so the middleware has them at import time."""
    from api.settings import _env_origins

    return _env_origins("CORS_ORIGINS")


app = FastAPI(
    title="Parking Monitor API",
    version="1.0.0",
    description="Real-time parking lot occupancy. Poll /api/v1/state to read.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins_from_env(),
    allow_methods=["GET"],
    allow_headers=["*"],
    max_age=3600,
)

# ── Routers ─────────────────────────────────────────────────────────────────
app.include_router(state.router, prefix="/api/v1", tags=["state"])
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(history.router, prefix="/api/v1", tags=["history"])
app.include_router(system.router, prefix="/api/v1", tags=["system"])
app.include_router(index.router, tags=["index"])

# ── Static files (mounted last — API routes above take priority) ────────────
app.mount("/assets", StaticFiles(directory="assets"), name="assets")
app.mount("/web", StaticFiles(directory="web", html=True), name="web")
