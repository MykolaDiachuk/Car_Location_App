"""GET /api/v1/state — latest parking snapshot.

Polling this endpoint marks the client as active and keeps the pipeline
running. If no one polls for ``IDLE_TIMEOUT`` seconds the camera is released
and the worker pauses. The first poll after idle returns the last cached
snapshot immediately (potentially stale); fresh data arrives ~1 s later.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from parking.models import StateResponse
from api.settings import Settings
from api.state_store import StateStore
from api.routes._helpers import build_state_response

router = APIRouter()


@router.get("/state", response_model=StateResponse)
def get_state(request: Request) -> StateResponse:
    """Return the latest parking snapshot.

    Returns 503 only on cold start (no snapshot yet); after that the latest
    cached state is always returned with ``stale`` so the frontend can
    decide how to render staleness.
    """
    store: StateStore = request.app.state.store
    settings: Settings = request.app.state.settings

    store.mark_activity()
    state, snapshot_at = store.get_state()
    if state is None:
        raise HTTPException(
            status_code=503,
            detail="Pipeline starting — no snapshot yet. Retry shortly.",
        )
    return build_state_response(state, snapshot_at, settings, store)
