"""Shared helpers used by multiple route modules."""
from __future__ import annotations

import time

from parking.models import ParkingState, StateResponse
from api.settings import Settings
from api.state_store import StateStore


def bev_dimensions() -> tuple[int, int]:
    """Return ``(BEV_WIDTH, BEV_HEIGHT)`` from the project config."""
    from config import ParkingConfig

    return ParkingConfig.BEV_WIDTH, ParkingConfig.BEV_HEIGHT


def build_state_response(
    state: ParkingState,
    snapshot_at_mono: float,
    settings: Settings,
    store: StateStore,
) -> StateResponse:
    """Wrap a ParkingState snapshot with the metadata the frontend needs."""
    bev_w, bev_h = bev_dimensions()
    age = max(0.0, time.monotonic() - snapshot_at_mono)
    return StateResponse(
        timestamp=state.timestamp,
        stale=age > settings.stale_threshold,
        pipeline_status=store.pipeline_status,
        bev_width=bev_w,
        bev_height=bev_h,
        total_spots=state.total_spots,
        occupied=state.occupied,
        free=state.free,
        occupancy_percent=state.occupancy_percent,
        spots=state.spots,
    )
