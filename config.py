"""Static configuration for the parking detection pipeline.

Values here describe the *physical* setup of the parking lot and the
detection algorithm. Every setting has a sensible default baked in — a
fresh deployment with only ``CAMERA_URL`` in ``.env`` will run with the
recommended values (temporal smoothing on, conservative confidence
threshold, etc.). Any of them can be overridden via environment variable
(typically through ``.env``); the configurator produces such a file
automatically.

Runtime / deployment options (database path, HTTP settings, idle timeout,
heartbeat) live in environment variables consumed by :mod:`api.settings`.

For a full reference of every option see ``docs/configuration.md``.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # reads .env if present; no-op otherwise

import numpy as np

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r, using default %d", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r, using default %f", name, raw, default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_src_points(default: list[list[float]]) -> np.ndarray:
    """Parse SRC_POINTS env var as JSON; fall back to default on any error."""
    raw = os.getenv("SRC_POINTS")
    if raw is None or raw == "":
        return np.array(default, dtype=np.float32)
    try:
        parsed = json.loads(raw)
        if (
            not isinstance(parsed, list)
            or len(parsed) != 4
            or not all(isinstance(p, list) and len(p) == 2 for p in parsed)
        ):
            raise ValueError("SRC_POINTS must be a list of 4 [x, y] pairs")
        return np.array(parsed, dtype=np.float32)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Invalid SRC_POINTS=%r (%s), using default", raw, e)
        return np.array(default, dtype=np.float32)


# Default 4 source-frame corners for the reference deployment. Treated as
# a fallback only — when the configurator exports a calibrated .env this
# is overridden via the SRC_POINTS env var.
_SRC_POINTS_DEFAULT: list[list[float]] = [
    [-303, -163],
    [2070, 339],
    [3165, 1062],
    [831, 1250],
]


class ParkingConfig:
    """Pipeline configuration — BEV geometry, YOLO settings, smoothing knobs."""

    # ── Perspective transform ───────────────────────────────────────────────
    # 4 camera-space points that define the parking quad.
    # Order: [Top-Left, Top-Right, Bottom-Right, Bottom-Left].
    # Values can be negative or outside the frame — that's normal when the
    # camera is mounted on a wall and looks down at an angle.
    SRC_POINTS: np.ndarray = _env_src_points(_SRC_POINTS_DEFAULT)

    # Bird's Eye View canvas size (pixels).
    BEV_WIDTH: int = _env_int("BEV_WIDTH", 1200)
    BEV_HEIGHT: int = _env_int("BEV_HEIGHT", 800)

    # ── Car footprint in BEV (pixels) ───────────────────────────────────────
    # Constant size — no perspective-depth correction yet.
    CAR_WIDTH: int = _env_int("CAR_WIDTH", 150)
    CAR_HEIGHT: int = _env_int("CAR_HEIGHT", 80)

    # Grid stride for the free-spot scan over the parking mask (pixels).
    CHECK_STEP: int = _env_int("CHECK_STEP", 20)

    # Where on the YOLO bbox to project into BEV:
    #   "bottom_center" — projected point is the bottom-middle of the BEV box
    #   "bottom_right"  — projected point is the bottom-right corner
    DETECTION_ANCHOR: str = os.getenv("DETECTION_ANCHOR", "bottom_right")

    # ── Asset & weight paths (absolute, resolved from project root) ─────────
    MODEL_PATH: str = str(_PROJECT_ROOT / "yolo26m.pt")
    MASK_PATH: str = str(_PROJECT_ROOT / "assets" / "parking_mask.png")
    ZONE_MASK_PATH: str = str(_PROJECT_ROOT / "assets" / "orientation_zones.png")

    # Camera RTSP URL — REQUIRED. Loaded from the CAMERA_URL env var
    # (typically set via .env). The API server refuses to start without it.
    CAMERA_URL: str | None = os.getenv("CAMERA_URL")

    # ── YOLO settings ───────────────────────────────────────────────────────
    # COCO class IDs we treat as vehicles: car, motorcycle, bus, truck.
    VEHICLE_CLASSES: list[int] = [2, 3, 5, 7]
    # Minimum detection confidence — boxes below this are dropped.
    CONF_THRESHOLD: float = _env_float("CONF_THRESHOLD", 0.35)

    # Post-detection dedupe: drop a smaller bbox if its intersection with a
    # larger one covers at least this fraction of the smaller bbox's area.
    # Catches the "two boxes on the same car" case that NMS misses when the
    # smaller box is mostly contained in the larger one.
    # Set to 1.0 to disable (only exact duplicates would be removed).
    OVERLAP_THRESHOLD: float = _env_float("OVERLAP_THRESHOLD", 0.8)

    # ── Temporal hysteresis (K-of-N detection smoothing) ────────────────────
    # A detection survives only if it (or a sufficiently-overlapping bbox)
    # appears in at least TEMPORAL_MIN_K of the last TEMPORAL_WINDOW_N frames.
    # See docs/temporal-smoothing.md for the full algorithm.
    TEMPORAL_SMOOTH_ENABLED: bool = _env_bool("TEMPORAL_SMOOTH_ENABLED", True)
    TEMPORAL_WINDOW_N: int = _env_int("TEMPORAL_WINDOW_N", 5)
    TEMPORAL_MIN_K: int = _env_int("TEMPORAL_MIN_K", 3)
    TEMPORAL_IOU_MATCH: float = _env_float("TEMPORAL_IOU_MATCH", 0.3)
    # History entries older than this are dropped before applying the K-of-N
    # filter. On idle wake-up this means stale history evaporates and the
    # first frame after wake passes through unfiltered (warm-up behaviour).
    TEMPORAL_MAX_AGE_SECONDS: float = _env_float("TEMPORAL_MAX_AGE_SECONDS", 10.0)

    @staticmethod
    def get_dst_points() -> np.ndarray:
        """Return the destination corners for the BEV perspective transform.

        Order matches :attr:`SRC_POINTS`: [TL, TR, BR, BL].
        """
        return np.float32([
            [0, 0],
            [ParkingConfig.BEV_WIDTH, 0],
            [ParkingConfig.BEV_WIDTH, ParkingConfig.BEV_HEIGHT],
            [0, ParkingConfig.BEV_HEIGHT],
        ])
