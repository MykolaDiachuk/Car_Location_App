"""Parking data models for serialization and API output."""
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class SpotStatus(str, Enum):
    FREE = "free"
    OCCUPIED = "occupied"


class SpotOrientation(str, Enum):
    PARALLEL = "parallel"
    PERPENDICULAR = "perpendicular"


class BBox(BaseModel):
    """Axis-aligned bounding box in BEV pixel coordinates."""
    x1: int
    y1: int
    x2: int
    y2: int


class NormalizedPoint(BaseModel):
    """Position normalized to 0.0–1.0 range relative to BEV dimensions.

    Frontend can multiply by map width/height to place markers
    on any resolution.
    """
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class ParkingSpot(BaseModel):
    """Single parking spot detected in current frame."""
    status: SpotStatus
    orientation: SpotOrientation
    center_bev: NormalizedPoint
    bbox_bev: BBox
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)


class ParkingState(BaseModel):
    """Full snapshot of parking lot occupancy at a point in time."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_spots: int
    occupied: int
    free: int
    occupancy_percent: float = Field(ge=0.0, le=100.0)
    spots: list[ParkingSpot]
