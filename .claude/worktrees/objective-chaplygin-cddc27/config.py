"""Parking system configuration."""
from pathlib import Path

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

    # Paths (absolute, resolved from project root)
    MODEL_PATH = str(_PROJECT_ROOT / "yolo11n.pt")
    MASK_PATH = str(_PROJECT_ROOT / "assets" / "parking_mask.png")
    ZONE_MASK_PATH = str(_PROJECT_ROOT / "assets" / "orientation_zones.png")

    # Camera
    # CAMERA_URL = "rtsp://admin:asertan12@192.168.0.172:5554/cam/realmonitor?channel=1&subtype=0"
    # CAMERA_URL = "rtsp://admin:asertan12@192.168.10.220/cam/realmonitor?channel=1&subtype=0"
    CAMERA_URL = "rtsp://admin:asertan12@192.168.0.120:5554/cam/realmonitor?channel=1&subtype=0"


    # YOLO settings
    VEHICLE_CLASSES = [2, 3, 5, 7]  # car, motorcycle, bus, truck
    CONF_THRESHOLD = 0.3

    @staticmethod
    def get_dst_points() -> np.ndarray:
        """Get destination points for BEV transformation."""
        return np.float32([
            [0, 0],
            [ParkingConfig.BEV_WIDTH, 0],
            [ParkingConfig.BEV_WIDTH, ParkingConfig.BEV_HEIGHT],
            [0, ParkingConfig.BEV_HEIGHT]
        ])
