"""Thread-safe shared state for the Parking Monitor API.

Encapsulates the mutable globals that previously lived at module scope in
``server.py``: latest snapshot, client activity timestamp, pipeline health
counters, and the worker's wake/shutdown events.

A single :class:`StateStore` instance is created in the FastAPI ``lifespan``
context manager and stored on ``app.state.store``. Routes mutate state only
through the methods defined here, never by touching globals.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from parking.models import ParkingState, PipelineStatus
from api.database import record_snapshot

logger = logging.getLogger(__name__)


class StateStore:
    """Holds the live state shared between the pipeline worker and HTTP routes.

    All methods are safe to call from any thread.
    """

    def __init__(self, record_interval: float) -> None:
        self._record_interval = record_interval

        # Snapshot cache
        self._state_lock = threading.Lock()
        self._latest_state: Optional[ParkingState] = None
        self._latest_state_at: float = 0.0  # monotonic timestamp
        self._last_record_at: float = 0.0

        # Client activity → keeps pipeline awake
        self._activity_lock = threading.Lock()
        self._last_activity_at: float = 0.0

        # Worker control
        self.wake_event = threading.Event()
        self.shutdown_event = threading.Event()

        # Health counters (single-thread writer = worker; readers = HTTP)
        self._pipeline_status: PipelineStatus = "starting"
        self._camera_connected: bool = False
        self._frames_processed: int = 0
        self._pipeline_errors: int = 0
        self._last_error: Optional[str] = None
        self._started_at: float = time.monotonic()

    # ── Snapshot cache ───────────────────────────────────────────────────────

    def set_state(self, state: ParkingState, *, force_record: bool = False) -> None:
        """Update the cached snapshot and (optionally) persist to DB.

        The active pipeline loop calls with ``force_record=False`` — DB writes
        are throttled by ``record_interval``. The idle-time heartbeat path
        passes ``force_record=True`` so the row always lands.
        """
        now = time.monotonic()
        with self._state_lock:
            self._latest_state = state
            self._latest_state_at = now
            self._frames_processed += 1

        if force_record or now - self._last_record_at >= self._record_interval:
            self._last_record_at = now
            try:
                record_snapshot(state)
            except Exception as exc:
                logger.warning("Failed to record snapshot to DB: %s", exc)

    def get_state(self) -> tuple[Optional[ParkingState], float]:
        """Return ``(latest_snapshot, monotonic_timestamp_when_set)``."""
        with self._state_lock:
            return self._latest_state, self._latest_state_at

    # ── Activity tracking ────────────────────────────────────────────────────

    def mark_activity(self) -> None:
        """Record that a client just polled — keeps the pipeline awake."""
        with self._activity_lock:
            self._last_activity_at = time.monotonic()
        self.wake_event.set()

    def is_active(self, now: float, idle_timeout: float) -> bool:
        """True if a client has polled within ``idle_timeout`` seconds."""
        with self._activity_lock:
            return (now - self._last_activity_at) < idle_timeout

    # ── Pipeline health ──────────────────────────────────────────────────────

    def set_pipeline_status(self, status: PipelineStatus) -> None:
        self._pipeline_status = status

    @property
    def pipeline_status(self) -> PipelineStatus:
        return self._pipeline_status

    def set_camera_connected(self, connected: bool) -> None:
        self._camera_connected = connected

    @property
    def camera_connected(self) -> bool:
        return self._camera_connected

    def record_error(self, exc: BaseException) -> None:
        """Increment the error counter and remember the latest error message."""
        self._pipeline_errors += 1
        self._last_error = f"{type(exc).__name__}: {exc}"

    @property
    def frames_processed(self) -> int:
        return self._frames_processed

    @property
    def pipeline_errors(self) -> int:
        return self._pipeline_errors

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def uptime_seconds(self) -> float:
        return time.monotonic() - self._started_at
