"""Parking occupancy analysis."""
from typing import TYPE_CHECKING
import cv2
import numpy as np

from parking.models import (
    BBox,
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
        anchor = getattr(config, "DETECTION_ANCHOR", "bottom_right")
        if anchor not in ("bottom_center", "bottom_right"):
            raise ValueError(f"Unknown DETECTION_ANCHOR: {anchor!r}")
        self.anchor = anchor
        self.zone_mask = self._load_image(config.ZONE_MASK_PATH, color=True)
        self.parking_mask = self._load_parking_mask(config.MASK_PATH)

        # Pre-compute binary masks + integral images for blue / green zones.
        # Used by area-vote orientation lookup in _find_free_spots — turns
        # per-candidate pixel counting from O(W·H) into O(1) per query.
        zb = self.zone_mask[:, :, 0]
        zg = self.zone_mask[:, :, 1]
        zr = self.zone_mask[:, :, 2]
        blue_bin  = ((zb > 200) & (zg < 50) & (zr < 50)).astype(np.uint8)
        green_bin = ((zg > 200) & (zb < 50) & (zr < 50)).astype(np.uint8)
        self._blue_integral  = cv2.integral(blue_bin)
        self._green_integral = cv2.integral(green_bin)

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
        """Read orientation zone at a single BEV point.

        Kept as a fallback / utility. The free-spot grid scan now uses
        `_orientation_by_area` instead, which is robust to single-pixel
        boundary noise.
        Green = parallel, Blue = perpendicular.
        """
        if not (0 <= y < self.zone_mask.shape[0] and 0 <= x < self.zone_mask.shape[1]):
            return SpotOrientation.PARALLEL
        b, g, r = self.zone_mask[y, x]
        if b > 200 and g < 50 and r < 50:
            return SpotOrientation.PERPENDICULAR
        return SpotOrientation.PARALLEL

    def _rect_sum(self, integral: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> int:
        """Sum of binary mask pixels in axis-aligned rect [x1, x2) × [y1, y2)."""
        # Clip to image bounds
        x1 = max(0, min(self.bev_w, x1))
        x2 = max(0, min(self.bev_w, x2))
        y1 = max(0, min(self.bev_h, y1))
        y2 = max(0, min(self.bev_h, y2))
        if x2 <= x1 or y2 <= y1:
            return 0
        # cv2.integral output has shape (H+1, W+1)
        return int(
            integral[y2, x2]
            - integral[y1, x2]
            - integral[y2, x1]
            + integral[y1, x1]
        )

    def _orientation_by_area(self, x: int, y: int) -> SpotOrientation:
        """Decide free-spot orientation by per-candidate zone-color coverage.

        Builds BOTH possible bounding boxes anchored at (x, y) — parallel
        (150×80) and perpendicular (80×150) — and asks each one:
            "How many of MY zone-color pixels fall inside me?"

        Whichever candidate has more matching material wins. This is robust
        to noisy zone boundaries: a candidate whose specific shape lines up
        with its zone wins even when a single anchor pixel happens to land
        on the wrong side.

        Both candidates share the same area (CAR_WIDTH × CAR_HEIGHT) so the
        raw counts are directly comparable — no normalization needed.
        Falls back to PARALLEL on tie or when neither zone is painted.
        """
        p_bb = self._spot_bbox(x, y, SpotOrientation.PARALLEL)
        pp_bb = self._spot_bbox(x, y, SpotOrientation.PERPENDICULAR)

        green_in_parallel  = self._rect_sum(self._green_integral, p_bb.x1, p_bb.y1, p_bb.x2, p_bb.y2)
        blue_in_perp       = self._rect_sum(self._blue_integral,  pp_bb.x1, pp_bb.y1, pp_bb.x2, pp_bb.y2)

        return (
            SpotOrientation.PERPENDICULAR if blue_in_perp > green_in_parallel
            else SpotOrientation.PARALLEL
        )

    def _orientation_for_det(
        self,
        x1: int, y1: int, x2: int, y2: int,
        transformer: "PerspectiveTransformer",
    ) -> SpotOrientation:
        """Determine orientation by majority-vote over zone-mask pixels inside the
        BEV-projected YOLO bounding box polygon.

        Projects all 4 camera-space corners into BEV, fills a polygon, then
        counts blue vs green pixels inside it.
        Blue-majority → PERPENDICULAR, green/neutral-majority → PARALLEL.
        Falls back to anchor-point method if the polygon is degenerate.
        """
        corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
        pts_bev = []
        for cx, cy in corners:
            px, py = transformer.transform_point(cx, cy)
            pts_bev.append([
                int(np.clip(px, 0, self.bev_w - 1)),
                int(np.clip(py, 0, self.bev_h - 1)),
            ])

        poly = np.zeros((self.bev_h, self.bev_w), dtype=np.uint8)
        cv2.fillPoly(poly, [np.array(pts_bev, dtype=np.int32)], 255)

        if not np.any(poly):
            # Degenerate polygon — fall back to single anchor-point lookup
            ax = x2 if self.anchor == "bottom_right" else (x1 + x2) // 2
            bx, by = transformer.transform_point(ax, y2)
            return self._orientation_at(
                int(np.clip(bx, 0, self.bev_w - 1)),
                int(np.clip(by, 0, self.bev_h - 1)),
            )

        inside = poly > 0
        b = self.zone_mask[:, :, 0]
        g = self.zone_mask[:, :, 1]
        r = self.zone_mask[:, :, 2]
        blue_count  = int(np.sum(inside & (b > 200) & (g < 50) & (r < 50)))
        green_count = int(np.sum(inside & (g > 200) & (b < 50) & (r < 50)))

        return (
            SpotOrientation.PERPENDICULAR if blue_count > green_count
            else SpotOrientation.PARALLEL
        )
    
    def _spot_bbox(self, x: int, y: int, orientation: SpotOrientation) -> BBox:
        """Bounding box of a parking spot anchored at (x, y) per DETECTION_ANCHOR."""
        bw = self.car_h if orientation == SpotOrientation.PERPENDICULAR else self.car_w
        bh = self.car_w if orientation == SpotOrientation.PERPENDICULAR else self.car_h
        if self.anchor == "bottom_right":
            return BBox(x1=x - bw, y1=y - bh, x2=x, y2=y)
        return BBox(x1=x - bw // 2, y1=y - bh, x2=x + bw // 2, y2=y)
    
    def _make_spot(
        self,
        spot_id: int,
        x: int,
        y: int,
        orientation: SpotOrientation,
        status: SpotStatus,
    ) -> ParkingSpot:
        return ParkingSpot(
            id=spot_id,
            status=status,
            orientation=orientation,
            bbox_bev=self._spot_bbox(x, y, orientation),
        )
    
    def _mark_occupied(
        self,
        mask: np.ndarray,
        points: list[tuple[int, int, SpotOrientation]],
    ) -> np.ndarray:
        """Black out the area of each detected vehicle on the mask."""
        result = mask.copy()
        for x, y, orientation in points:
            bb = self._spot_bbox(x, y, orientation)
            cx1, cy1 = max(0, bb.x1), max(0, bb.y1)
            cx2, cy2 = min(result.shape[1], bb.x2), min(result.shape[0], bb.y2)
            cv2.rectangle(result, (cx1, cy1), (cx2, cy2), 0, -1)
        return result
    
    def _find_free_spots(self, mask: np.ndarray) -> list[tuple[int, int, SpotOrientation]]:
        """Scan the mask with a grid and collect spots that are fully white (free)."""
        spots: list[tuple[int, int, SpotOrientation]] = []
        step = self.config.CHECK_STEP
        h, w = mask.shape
    
        max_dim = max(self.car_w, self.car_h)
        if self.anchor == "bottom_right":
            x_start, x_stop = max_dim, w
        else:
            x_start, x_stop = max_dim // 2, w - max_dim // 2
        for y in range(max_dim, h, step):
            for x in range(x_start, x_stop, step):
                o = self._orientation_by_area(x, y)
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

        # Pre-compute BEV anchor + orientation for each detection.
        # Orientation uses full bbox polygon projection for robustness
        # (vs single-anchor-point lookup used for free spots).
        occupied_points: list[tuple[int, int, SpotOrientation]] = []
        for det in detections:
            x1, y1, x2, y2 = map(int, det[:4])
            ax = x2 if self.anchor == "bottom_right" else (x1 + x2) // 2
            px, py = transformer.transform_point(ax, y2)
            px = max(0, min(self.bev_w - 1, px))
            py = max(0, min(self.bev_h - 1, py))
            o = self._orientation_for_det(x1, y1, x2, y2, transformer)
            occupied_points.append((px, py, o))

        temp_mask = self._mark_occupied(self.parking_mask.copy(), occupied_points)
        free_spots = self._find_free_spots(temp_mask)

        result = cv2.addWeighted(bev_view, 0.7, self.zone_mask, 0.3, 0)
        next_id = 0

        for x, y, o in occupied_points:
            self._draw_spot(result, x, y, o, occupied=True)
            all_spots.append(self._make_spot(next_id, x, y, o, SpotStatus.OCCUPIED))
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
