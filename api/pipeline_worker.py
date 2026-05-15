"""Background thread that drives the parking pipeline.

The worker is activity-driven: it processes frames continuously while at
least one client has polled ``/api/v1/state`` recently (within
``IDLE_TIMEOUT``). When no clients are active the camera is released to free
hardware resources.

To keep the history database continuous and to guarantee that a returning
visitor sees recent data, the worker still wakes briefly every
``HEARTBEAT_INTERVAL`` seconds while idle, grabs a single frame, writes it
to the DB, and goes back to sleep.

The four pipeline-status values exposed to clients mirror the worker's
internal state machine:

``starting``
    Worker is initialising or reconnecting to the camera.
``running``
    Actively processing frames at ``ANALYSIS_INTERVAL``.
``idle``
    No recent client polls — camera released, worker sleeping.
``error``
    Camera unreachable or pipeline raised; auto-retrying with backoff.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import cv2

from api.settings import Settings
from api.state_store import StateStore
from parking.pipeline import ParkingPipeline

logger = logging.getLogger(__name__)


class PipelineWorker:
    """Owns the background thread that runs the parking pipeline."""

    def __init__(
        self,
        settings: Settings,
        store: StateStore,
        pipeline: ParkingPipeline,
        camera_url: str,
    ) -> None:
        self._settings = settings
        self._store = store
        self._pipeline = pipeline
        self._camera_url = camera_url

        self._thread: Optional[threading.Thread] = None
        self._cap: Optional[cv2.VideoCapture] = None
        self._last_heartbeat_at: float = 0.0
        self._reconnect_backoff: float = settings.reconnect_backoff_initial

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Launch the worker thread (daemon)."""
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="pipeline-worker"
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Signal shutdown and wait for the thread to exit."""
        self._store.shutdown_event.set()
        self._store.wake_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._release_camera()

    # ── Main loop ────────────────────────────────────────────────────────────

    def _run(self) -> None:
        """Activity-driven pipeline loop with idle-time heartbeats."""
        # Start the heartbeat clock at server boot so the first heartbeat
        # fires HEARTBEAT_INTERVAL seconds later, not immediately.
        self._last_heartbeat_at = time.monotonic()

        while not self._store.shutdown_event.is_set():
            now = time.monotonic()
            active = self._store.is_active(now, self._settings.idle_timeout)

            if not active:
                self._handle_idle(now)
                continue

            self._handle_active()

        self._release_camera()
        logger.info("Pipeline worker stopped")

    # ── Idle branch ──────────────────────────────────────────────────────────

    def _handle_idle(self, now: float) -> None:
        """Release the camera, optionally fire a heartbeat snapshot, then wait."""
        if self._cap is not None:
            logger.info("Pipeline going idle — releasing camera")
            self._release_camera()

        elapsed = now - self._last_heartbeat_at
        if self._settings.heartbeat_interval > 0 and elapsed >= self._settings.heartbeat_interval:
            self._fire_heartbeat()
            return

        # Otherwise mark idle (unless we're stuck in error state) and sleep.
        if self._store.pipeline_status != "error":
            self._store.set_pipeline_status("idle")

        # Cap the wait at 60 s so shutdown / heartbeat re-checks stay responsive.
        if self._settings.heartbeat_interval > 0:
            until_heartbeat = max(1.0, self._settings.heartbeat_interval - elapsed)
            wait_s = min(until_heartbeat, 60.0)
        else:
            wait_s = 5.0
        self._store.wake_event.wait(timeout=wait_s)
        self._store.wake_event.clear()

    def _fire_heartbeat(self) -> None:
        """Take one idle-time snapshot and reset the heartbeat clock."""
        self._store.set_pipeline_status("starting")
        logger.info("Heartbeat — taking idle background snapshot")
        ok = self._take_heartbeat_snapshot()
        self._last_heartbeat_at = time.monotonic()
        if ok:
            logger.info("Heartbeat snapshot recorded")
            self._store.set_pipeline_status("idle")
        else:
            msg = f"Heartbeat failed: camera unreachable ({self._redact_url(self._camera_url)})"
            logger.warning(msg)
            self._store.record_error(RuntimeError(msg))
            self._store.set_pipeline_status("error")

    def _take_heartbeat_snapshot(self) -> bool:
        """Connect, grab one frame, process, force-record, release.

        Used when no clients are online but we still want a snapshot every
        ``HEARTBEAT_INTERVAL`` seconds so the history DB stays continuous and
        the next visitor sees fresh-ish data immediately.
        """
        cap = self._open_camera()
        if cap is None:
            return False
        try:
            # Discard buffered frames — RTSP often returns stale data right
            # after reconnect.
            warmup = max(0, self._settings.heartbeat_warmup_frames - 1)
            for _ in range(warmup):
                cap.read()
            ret, frame = cap.read()
            if not ret or frame is None:
                return False
            # Clear temporal hysteresis before an isolated heartbeat shot —
            # any history is from a previous wake window, so it would suppress
            # this single frame's detections and record zero cars.
            if getattr(self._pipeline, "tracker", None) is not None:
                self._pipeline.tracker.reset()
            result = self._pipeline.process_frame(frame)
            self._store.set_state(result.state, force_record=True)
            return True
        finally:
            try:
                cap.release()
            except Exception:
                pass
            self._store.set_camera_connected(False)

    # ── Active branch ────────────────────────────────────────────────────────

    def _handle_active(self) -> None:
        """Connect (if needed) and process a single frame."""
        if self._cap is None:
            if not self._connect_for_active():
                return

        ret, frame = self._cap.read()
        if not ret:
            logger.warning("Frame read failed — reconnecting")
            self._release_camera()
            return

        try:
            result = self._pipeline.process_frame(frame)
            self._store.set_state(result.state)
            self._store.set_pipeline_status("running")
            # Active processing keeps the DB fresh — reset heartbeat clock so
            # we don't double-snapshot right after clients leave.
            self._last_heartbeat_at = time.monotonic()
        except Exception as exc:
            logger.exception("Pipeline error")
            self._store.record_error(exc)
            self._store.set_pipeline_status("error")

        if self._store.shutdown_event.wait(timeout=self._settings.analysis_interval):
            return

    def _connect_for_active(self) -> bool:
        """Connect on idle→active transition. Returns True on success.

        On failure, sleeps with exponential backoff and returns False so the
        main loop can retry.
        """
        self._store.set_pipeline_status("starting")
        logger.info("Activity detected — connecting to camera")

        # Drop temporal-hysteresis history accumulated before the idle gap —
        # otherwise the first frame after wake-up gets voted down by stale
        # entries and the user sees "0 cars" on a full lot.
        if getattr(self._pipeline, "tracker", None) is not None:
            self._pipeline.tracker.reset()

        cap = self._open_camera()
        if cap is None:
            self._store.set_pipeline_status("error")
            err_msg = f"Camera unreachable: {self._redact_url(self._camera_url)}"
            logger.warning(f"{err_msg} — retrying in {self._reconnect_backoff:.0f}s")
            self._store.record_error(RuntimeError(err_msg))
            if self._store.shutdown_event.wait(timeout=self._reconnect_backoff):
                return False
            self._reconnect_backoff = min(
                self._reconnect_backoff * 2, self._settings.reconnect_backoff_max
            )
            return False

        self._cap = cap
        self._reconnect_backoff = self._settings.reconnect_backoff_initial
        logger.info("Camera connected")
        return True

    # ── Camera helpers ───────────────────────────────────────────────────────

    def _open_camera(self) -> Optional[cv2.VideoCapture]:
        """Open the RTSP stream. Returns None if the connection fails."""
        cap = cv2.VideoCapture(self._camera_url)
        if not cap.isOpened():
            try:
                cap.release()
            except Exception:
                pass
            self._store.set_camera_connected(False)
            return None
        self._store.set_camera_connected(True)
        return cap

    def _release_camera(self) -> None:
        """Release the active capture handle if one is open."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        self._store.set_camera_connected(False)

    @staticmethod
    def _redact_url(url: str) -> str:
        """Strip credentials from RTSP URL for logs and health output."""
        if "@" not in url:
            return url
        scheme, rest = url.split("://", 1) if "://" in url else ("", url)
        _, host_part = rest.split("@", 1)
        return f"{scheme}://{host_part}" if scheme else host_part
