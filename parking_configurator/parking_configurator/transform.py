from __future__ import annotations

from typing import Sequence

import cv2
import numpy as np


def _validate_dims(width: int, height: int) -> None:
    if not (400 <= width <= 4000 and 400 <= height <= 4000):
        raise ValueError("BEV width and height must be in [400, 4000]")


def bev_from_frame(
    frame: np.ndarray,
    src_points: Sequence[Sequence[float]],
    width: int,
    height: int,
) -> np.ndarray:
    """Warp a source frame into a bird's-eye-view canvas.

    src_points is 4 corners in source-frame pixel coords ordered [TL, TR, BR, BL].
    Coordinates may be negative or beyond frame bounds.
    """
    _validate_dims(width, height)
    src = np.asarray(src_points, dtype=np.float32)
    if src.shape != (4, 2):
        raise ValueError("src_points must be a 4x2 array")
    dst = np.array(
        [
            [0, 0],
            [width - 1, 0],
            [width - 1, height - 1],
            [0, height - 1],
        ],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(frame, matrix, (width, height))
