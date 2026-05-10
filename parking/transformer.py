"""Perspective transformation for Bird's Eye View."""
from typing import TYPE_CHECKING
import cv2
import numpy as np

if TYPE_CHECKING:
    from config import ParkingConfig


class PerspectiveTransformer:
    """Transforms camera perspective to Bird's Eye View."""

    def __init__(self, config: "ParkingConfig") -> None:
        src_points = config.SRC_POINTS
        dst_points = config.get_dst_points()
        self.bev_width = config.BEV_WIDTH
        self.bev_height = config.BEV_HEIGHT
        self.M = cv2.getPerspectiveTransform(src_points, dst_points)

    def transform(self, frame: np.ndarray) -> np.ndarray:
        """Transform frame to Bird's Eye View."""
        return cv2.warpPerspective(frame, self.M, (self.bev_width, self.bev_height))

    def transform_point(self, x: int, y: int) -> tuple[int, int]:
        """Transform a single point to BEV coordinates.

        Returns the raw projected point (may fall outside the BEV frame).
        Callers are responsible for clamping if they need an in-frame point.
        """
        point = np.array([[[x, y]]], dtype=np.float32)
        transformed = cv2.perspectiveTransform(point, self.M)
        rx, ry = transformed[0][0].astype(int)
        return int(rx), int(ry)
