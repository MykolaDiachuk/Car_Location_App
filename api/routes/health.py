"""GET /api/v1/health — operational status for external monitors.

Safe to poll continuously: this endpoint does NOT mark client activity, so
hitting it will not keep the pipeline awake.
"""
from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Request

from parking.models import CameraHealth, HealthResponse, PipelineHealth
from api.state_store import StateStore
from api.routes._helpers import bev_dimensions

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def get_health(request: Request) -> HealthResponse:
    """Return server uptime, pipeline counters, and camera connectivity."""
    store: StateStore = request.app.state.store
    bev_w, bev_h = bev_dimensions()

    state, _ = store.get_state()

    if store.pipeline_status == "error":
        overall = "error"
    elif state is None:
        overall = "starting"
    else:
        overall = "ok"

    last_frame_at: datetime | None = state.timestamp if state is not None else None

    return HealthResponse(
        status=overall,
        uptime_seconds=round(store.uptime_seconds(), 1),
        pipeline=PipelineHealth(
            status=store.pipeline_status,
            frames_processed=store.frames_processed,
            errors=store.pipeline_errors,
            last_error=store.last_error,
        ),
        camera=CameraHealth(
            connected=store.camera_connected,
            last_frame_at=last_frame_at,
        ),
        bev_width=bev_w,
        bev_height=bev_h,
    )
