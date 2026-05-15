"""Static configuration for the parking detection pipeline.

Values here describe the *physical* setup of the parking lot and the
detection algorithm — they rarely change after initial calibration.
Runtime / deployment options (database path, HTTP settings, idle timeout,
heartbeat) live in environment variables consumed by :mod:`api.settings`.

For a full reference of every option see ``docs/configuration.md``.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # reads .env if present; no-op otherwise

import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parent


class ParkingConfig:
    """Pipeline configuration — BEV geometry, YOLO settings, smoothing knobs."""

    # ── Perspective transform ───────────────────────────────────────────────
    # 4 camera-space points that define the parking quad.
    # Order: [Top-Left, Top-Right, Bottom-Right, Bottom-Left].
    # Values can be negative or outside the frame — that's normal when the
    # camera is mounted on a wall and looks down at an angle.
    SRC_POINTS: np.ndarray = np.float32([
        [-303, -163],
        [2070, 339],
        [3165, 1062],
        [831, 1250],
    ])

    # Bird's Eye View canvas size (pixels).
    BEV_WIDTH: int = 1200
    BEV_HEIGHT: int = 800

    # ── Car footprint in BEV (pixels) ───────────────────────────────────────
    # Constant size — no perspective-depth correction yet.
    CAR_WIDTH: int = 150
    CAR_HEIGHT: int = 80

    # Grid stride for the free-spot scan over the parking mask (pixels).
    CHECK_STEP: int = 20

    # Where on the YOLO bbox to project into BEV:
    #   "bottom_center" — projected point is the bottom-middle of the BEV box
    #   "bottom_right"  — projected point is the bottom-right corner
    DETECTION_ANCHOR: str = "bottom_right"

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
    CONF_THRESHOLD: float = 0.35

    # Post-detection dedupe: drop a smaller bbox if its intersection with a
    # larger one covers at least this fraction of the smaller bbox's area.
    # Catches the "two boxes on the same car" case that NMS misses when the
    # smaller box is mostly contained in the larger one.
    # Set to 1.0 to disable (only exact duplicates would be removed).
    OVERLAP_THRESHOLD: float = 0.8

    # ── Temporal hysteresis (K-of-N detection smoothing) ────────────────────
    # A detection survives only if it (or a sufficiently-overlapping bbox)
    # appears in at least TEMPORAL_MIN_K of the last TEMPORAL_WINDOW_N frames.
    # See docs/temporal-smoothing.md for the full algorithm.
    TEMPORAL_SMOOTH_ENABLED: bool = os.getenv("TEMPORAL_SMOOTH_ENABLED", "true").lower() == "true"
    TEMPORAL_WINDOW_N: int = int(os.getenv("TEMPORAL_WINDOW_N", "5"))
    TEMPORAL_MIN_K: int = int(os.getenv("TEMPORAL_MIN_K", "3"))
    TEMPORAL_IOU_MATCH: float = float(os.getenv("TEMPORAL_IOU_MATCH", "0.3"))
    # History entries older than this are dropped before applying the K-of-N
    # filter. On idle wake-up this means stale history evaporates and the
    # first frame after wake passes through unfiltered (warm-up behaviour).
    TEMPORAL_MAX_AGE_SECONDS: float = float(os.getenv("TEMPORAL_MAX_AGE_SECONDS", "10.0"))

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
