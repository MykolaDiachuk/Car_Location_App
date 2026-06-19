"""Synthetic ParkingState generator — no camera or YOLO required.

Usage
-----
Standalone (verify JSON shape):
    python -m api.mock_state

As a background thread in server.py (MOCK_MODE = True):
    from api.mock_state import start_mock_worker
"""
import random
import time
from datetime import datetime, timezone
from typing import Callable

from parking.models import (
    BBox,
    NormalizedPoint,
    ParkingSpot,
    ParkingState,
    SpotOrientation,
    SpotStatus,
)

# (norm_x, norm_y, orientation)
_MOCK_SPOTS = [
    (0.15, 0.65, "parallel"),
    (0.25, 0.67, "parallel"),
    (0.35, 0.69, "parallel"),
    (0.48, 0.55, "perpendicular"),
    (0.56, 0.57, "perpendicular"),
    (0.64, 0.59, "perpendicular"),
    (0.72, 0.53, "perpendicular"),
]

_BEV_W = 1200
_BEV_H = 800
_CAR_W = 150
_CAR_H = 80


def _build_state(tick: int) -> ParkingState:
    spots = []
    occupied = 0
    for i, (nx, ny, ori) in enumerate(_MOCK_SPOTS):
        is_occ = (i + tick) % 2 == 0
        px, py = int(nx * _BEV_W), int(ny * _BEV_H)
        spots.append(
            ParkingSpot(
                status=SpotStatus.OCCUPIED if is_occ else SpotStatus.FREE,
                orientation=(
                    SpotOrientation.PARALLEL
                    if ori == "parallel"
                    else SpotOrientation.PERPENDICULAR
                ),
                center_bev=NormalizedPoint(x=nx, y=ny),
                bbox_bev=BBox(
                    x1=px - _CAR_W // 2,
                    y1=py - _CAR_H // 2,
                    x2=px + _CAR_W // 2,
                    y2=py + _CAR_H // 2,
                ),
                confidence=round(random.uniform(0.6, 0.99), 2),
            )
        )
        if is_occ:
            occupied += 1
    free = len(spots) - occupied
    return ParkingState(
        timestamp=datetime.now(timezone.utc),
        total_spots=len(spots),
        occupied=occupied,
        free=free,
        occupancy_percent=round(occupied / len(spots) * 100, 1),
        spots=spots,
    )


def start_mock_worker(setter: Callable[[ParkingState], None]) -> None:
    """Run forever, calling setter(state) every 2 seconds."""
    tick = 0
    while True:
        setter(_build_state(tick))
        tick += 1
        time.sleep(2)


if __name__ == "__main__":
    print(_build_state(0).model_dump_json(indent=2))
