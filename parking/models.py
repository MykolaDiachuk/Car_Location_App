"""Parking data models for serialization and API output."""
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

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


class ParkingSpot(BaseModel):
    """Single parking spot detected in current frame.

    `id` is unique within a single response but NOT stable across responses
    (detection-based; spots can appear/disappear between frames).
    """
    id: int
    status: SpotStatus
    orientation: SpotOrientation
    bbox_bev: BBox


class ParkingState(BaseModel):
    """Full snapshot of parking lot occupancy at a point in time."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_spots: int
    occupied: int
    free: int
    occupancy_percent: float = Field(ge=0.0, le=100.0)
    spots: list[ParkingSpot]


PipelineStatus = Literal["running", "idle", "starting", "error"]


class StateResponse(BaseModel):
    """API response for /api/v1/state.

    Wraps a ParkingState snapshot with metadata the frontend needs:
    snapshot time, BEV canvas size for coordinate scaling, freshness
    info, and pipeline status for showing UI hints (loading, offline).
    """
    timestamp: datetime
    stale: bool
    pipeline_status: PipelineStatus
    bev_width: int
    bev_height: int
    total_spots: int
    occupied: int
    free: int
    occupancy_percent: float = Field(ge=0.0, le=100.0)
    spots: list[ParkingSpot]


class HistoryPoint(BaseModel):
    """Single data point for occupancy history charts."""
    timestamp: datetime
    total_spots: int
    occupied: int
    free: int
    occupancy_percent: float = Field(ge=0.0, le=100.0)


class HistoryResponse(BaseModel):
    """API response for /api/v1/history — historical occupancy for charts."""
    period_from: datetime
    period_to: datetime
    bucket_seconds: int = Field(
        description="Aggregation window in seconds. 0 = raw data (no aggregation)."
    )
    points: list[HistoryPoint]


class CameraHealth(BaseModel):
    connected: bool
    last_frame_at: datetime | None = None


class PipelineHealth(BaseModel):
    status: PipelineStatus
    frames_processed: int
    errors: int
    last_error: str | None = None


class HealthResponse(BaseModel):
    """API response for /api/v1/health — operational status for monitoring."""
    status: Literal["ok", "degraded", "error", "starting"]
    uptime_seconds: float
    pipeline: PipelineHealth
    camera: CameraHealth
    bev_width: int
    bev_height: int
