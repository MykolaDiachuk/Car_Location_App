"""Parking system configuration."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # reads .env if present; no-op otherwise

import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parent


class ParkingConfig:
    """Configuration for parking detection system."""

    # Perspective transform source points
    # Order: [Top-Left, Top-Right, Bottom-Right, Bottom-Left]
    SRC_POINTS = np.float32([
        [-303, -163],
        [2070, 339],
        [3165, 1062],
        [831, 1250]
    ])

    # Bird's Eye View dimensions
    BEV_WIDTH = 1200
    BEV_HEIGHT = 800

    # Car size in BEV (pixels)
    CAR_WIDTH = 150
    CAR_HEIGHT = 80

    # Grid scan step for free spot search
    CHECK_STEP = 20

    # Where on the YOLO bbox to anchor the BEV spot:
    #   "bottom_center" — projected point is the bottom-middle of the BEV box
    #   "bottom_right"  — projected point is the bottom-right corner of the BEV box
    DETECTION_ANCHOR = "bottom_right"

    # Paths (absolute, resolved from project root)
    MODEL_PATH = str(_PROJECT_ROOT / "yolo26s.pt")
    MASK_PATH = str(_PROJECT_ROOT / "assets" / "parking_mask.png")
    ZONE_MASK_PATH = str(_PROJECT_ROOT / "assets" / "orientation_zones.png")

    CAMERA_URL = os.getenv("CAMERA_URL")

    # YOLO settings
    VEHICLE_CLASSES = [2, 3, 5, 7]  # car, motorcycle, bus, truck
    CONF_THRESHOLD = 0.4

    # Post-detection dedupe — drop a smaller bbox if its intersection with a
    # larger one covers at least this fraction of the smaller bbox's area.
    # Catches the "two boxes on the same car" case that NMS misses when the
    # smaller box is mostly contained in the larger one.
    # Set to 1.0 to disable (only exact duplicates would be removed).
    OVERLAP_THRESHOLD = 0.8

    @staticmethod
    def get_dst_points() -> np.ndarray:
        """Get destination points for BEV transformation."""
        return np.float32([
            [0, 0],
            [ParkingConfig.BEV_WIDTH, 0],
            [ParkingConfig.BEV_WIDTH, ParkingConfig.BEV_HEIGHT],
            [0, ParkingConfig.BEV_HEIGHT]
        ])
