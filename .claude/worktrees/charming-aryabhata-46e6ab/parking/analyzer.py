"""Parking occupancy analysis."""
from typing import TYPE_CHECKING
import cv2
import numpy as np

from parking.models import (
    BBox,
    NormalizedPoint,
    ParkingSpot,
    ParkingState,
    SpotOrientation,
    SpotStatus,
)

if TYPE_CHECKING:
    from config import ParkingConfig
    from parking.transformer import PerspectiveTransformer


class ParkingAnalyzer:
    """Analyzes parking occupancy using BEV image and orientation zones."""

    def __init__(self, config: "ParkingConfig") -> None:
        self.config = config
        self.car_w = config.CAR_WIDTH
        self.car_h = config.CAR_HEIGHT
        self.bev_w = config.BEV_WIDTH
        self.bev_h = config.BEV_HEIGHT
        self.zone_mask = self._load_image(config.ZONE_MASK_PATH, color=True)
        self.parking_mask = self._load_parking_mask(config.MASK_PATH)

    def _load_image(self, path: str, color: bool) -> np.ndarray:
        img = cv2.imread(path) if color else cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            h, w = self.config.BEV_HEIGHT, self.config.BEV_WIDTH
            return (
                np.zeros((h, w, 3), dtype=np.uint8)
                if color
                else np.full((h, w), 255, dtype=np.uint8)
            )
        if img.shape[:2] != (self.config.BEV_HEIGHT, self.config.BEV_WIDTH):
            img = cv2.resize(
                img,
                (self.config.BEV_WIDTH, self.config.BEV_HEIGHT),
                interpolation=cv2.INTER_NEAREST
            )
        return img

    def _load_parking_mask(self, path: str) -> np.ndarray:
        mask = self._load_image(path, color=False)
        _, mask = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
        return mask

    def _orientation_at(self, x: int, y: int) -> SpotOrientation:
        """Read orientation zone at (x, y). Green = parallel, Blue = perpendicular."""
        if not (0 <= y < self.zone_mask.shape[0] and 0 <= x < self.zone_mask.shape[1]):
            return SpotOrientation.PARALLEL
        b, g, r = self.zone_mask[y, x]
        if b > 200 and g < 50 and r < 50:
            return SpotOrientation.PERPENDICULAR
        return SpotOrientation.PARALLEL
    
    def _spot_bbox(self, x: int, y: int, orientation: SpotOrientation) -> BBox:
        """Bounding box of a parking spot centered at (x, y)."""
        if orientation == SpotOrientation.PERPENDICULAR:
            return BBox(x1=x - self.car_h // 2, y1=y - self.car_w, x2=x + self.car_h // 2, y2=y)
        return BBox(x1=x - self.car_w // 2, y1=y - self.car_h, x2=x + self.car_w // 2, y2=y)
    
    def _normalize(self, x: int, y: int) -> NormalizedPoint:
        return NormalizedPoint(x=round(x / self.bev_w, 4), y=round(y / self.bev_h, 4))
    
    def _make_spot(
        self,
        spot_id: int,
        x: int,
        y: int,
        orientation: SpotOrientation,
        status: SpotStatus,
        confidence: float = 1.0,
    ) -> ParkingSpot:
        return ParkingSpot(
            id=spot_id,
            status=status,
            orientation=orientation,
            center_bev=self._normalize(x, y),
            bbox_bev=self._spot_bbox(x, y, orientation),
            confidence=confidence,
        )
    
    def _mark_occupied(self, mask: np.ndarray, points: list[tuple[int, int]]) -> np.ndarray:
        """Black out the area of each detected vehicle on the mask."""
        result = mask.copy()
        for x, y in points:
            bb = self._spot_bbox(x, y, self._orientation_at(x, y))
            cx1, cy1 = max(0, bb.x1), max(0, bb.y1)
            cx2, cy2 = min(result.shape[1], bb.x2), min(result.shape[0], bb.y2)
            cv2.rectangle(result, (cx1, cy1), (cx2, cy2), 0, -1)
        return result
    
    def _find_free_spots(self, mask: np.ndarray) -> list[tuple[int, int, SpotOrientation]]:
        """Scan the mask with a grid and collect spots that are fully white (free)."""
        spots: list[tuple[int, int, SpotOrientation]] = []
        step = self.config.CHECK_STEP
        h, w = mask.shape
    
        for y in range(self.car_h, h, step):
            for x in range(self.car_w // 2, w - self.car_w // 2, step):
                o = self._orientation_at(x, y)
                bb = self._spot_bbox(x, y, o)
    
                if bb.x1 < 0 or bb.y1 < 0 or bb.x2 > w or bb.y2 > h:
                    continue
    
                roi = mask[bb.y1:bb.y2, bb.x1:bb.x2]
                expected = (
                    (self.car_w, self.car_h)
                    if o == SpotOrientation.PERPENDICULAR
                    else (self.car_h, self.car_w)
                )
                if roi.shape == expected and np.all(roi == 255):
                    spots.append((x, y, o))
                    cv2.rectangle(mask, (bb.x1, bb.y1), (bb.x2, bb.y2), 0, -1)
    
        return spots
    
    def _draw_spot(
        self,
        img: np.ndarray,
        x: int,
        y: int,
        orientation: SpotOrientation,
        occupied: bool,
    ) -> None:
        color = (0, 0, 255) if occupied else (0, 255, 0)
        label = "CAR" if occupied else "FREE"
        bb = self._spot_bbox(x, y, orientation)
        cv2.rectangle(img, (bb.x1, bb.y1), (bb.x2, bb.y2), color, 2)
        cv2.putText(img, label, (bb.x1, bb.y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
    
    def analyze(
        self,
        bev_view: np.ndarray,
        detections: list[np.ndarray],
        transformer: "PerspectiveTransformer",
    ) -> tuple[np.ndarray, ParkingState]:
        """Return annotated BEV image and structured parking state."""
        all_spots: list[ParkingSpot] = []
    
        occupied_points: list[tuple[int, int, float]] = []
        for det in detections:
            x1, y1, x2, y2 = map(int, det[:4])
            conf = float(det[4])
            point = transformer.transform_point((x1 + x2) // 2, y2)
            if point is not None:
                occupied_points.append((*point, conf))
    
        mask_points = [(x, y) for x, y, _ in occupied_points]
        temp_mask = self._mark_occupied(self.parking_mask.copy(), mask_points)
        free_spots = self._find_free_spots(temp_mask)
    
        result = cv2.addWeighted(bev_view, 0.7, self.zone_mask, 0.3, 0)
        next_id = 0

        for x, y, conf in occupied_points:
            o = self._orientation_at(x, y)
            self._draw_spot(result, x, y, o, occupied=True)
            all_spots.append(self._make_spot(next_id, x, y, o, SpotStatus.OCCUPIED, confidence=conf))
            next_id += 1

        for x, y, o in free_spots:
            self._draw_spot(result, x, y, o, occupied=False)
            all_spots.append(self._make_spot(next_id, x, y, o, SpotStatus.FREE))
            next_id += 1
    
        occupied_count = len(occupied_points)
        free_count = len(free_spots)
        total = occupied_count + free_count
    
        state = ParkingState(
            total_spots=total,
            occupied=occupied_count,
            free=free_count,
            occupancy_percent=round(occupied_count / total * 100, 1) if total > 0 else 0.0,
            spots=all_spots,
        )
    
        return result, state
