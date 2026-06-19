"""Shared application state passed between tabs."""
from dataclasses import dataclass, field
import numpy as np


@dataclass
class AppState:
    """Mutable state shared across all tabs."""

    # Camera
    camera_url: str = ""

    # Captured frame (original resolution)
    frame: np.ndarray | None = None

    # BEV transform matrix and output image
    bev_matrix: np.ndarray | None = None
    bev_image: np.ndarray | None = None

    # SRC_POINTS: 4 x 2 float array
    src_points: np.ndarray = field(
        default_factory=lambda: np.float32([
            [0, 0], [1920, 0], [1920, 1080], [0, 1080]
        ])
    )

    # BEV canvas size
    bev_width: int = 1200
    bev_height: int = 800
