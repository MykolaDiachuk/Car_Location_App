"""Vehicle detection using YOLO."""
from typing import TYPE_CHECKING
import numpy as np
from ultralytics import YOLO

if TYPE_CHECKING:
    from config import ParkingConfig


class VehicleDetector:
    """YOLO-based vehicle detector."""

    def __init__(self, config: "ParkingConfig") -> None:
        self.model = YOLO(config.MODEL_PATH)
        self.classes = config.VEHICLE_CLASSES
        self.conf = config.CONF_THRESHOLD
        self.overlap_threshold = getattr(config, "OVERLAP_THRESHOLD", 0.8)

    def detect(self, frame: np.ndarray) -> list[np.ndarray]:
        """Detect vehicles in frame.

        Returns:
            List of detections, each as [x1, y1, x2, y2, confidence].
            Overlapping duplicates (one bbox mostly contained in another)
            are removed via _dedupe_overlapping().
        """
        results = self.model.predict(
            source=frame,
            conf=self.conf,
            classes=self.classes,
            verbose=False
        )

        detections = []
        if len(results) > 0:
            for box in results[0].boxes:
                coords = box.xyxy[0].cpu().numpy()
                conf = box.conf[0].cpu().numpy()
                detections.append(np.append(coords, conf))

        return self._dedupe_overlapping(detections, self.overlap_threshold)

    @staticmethod
    def _dedupe_overlapping(
        detections: list[np.ndarray],
        threshold: float,
    ) -> list[np.ndarray]:
        """Remove smaller bbox when it's >= `threshold` contained in a larger one.

        Uses IoSmaller (intersection / area_of_smaller) instead of IoU because
        when YOLO returns two boxes on the same car, the smaller one is often
        almost entirely inside the larger one, but the IoU stays low.

        Algorithm:
          1. Sort by area descending (largest first)
          2. Walk pairs (large, small) — if intersection covers >= threshold
             of the smaller box's area, drop the smaller one
          3. Already-dropped boxes don't suppress further candidates

        threshold = 1.0 effectively disables the filter (only exact full
        containment would match).
        """
        if len(detections) <= 1 or threshold >= 1.0:
            return detections

        # Pre-compute areas; sort indices by area descending
        areas = [
            (i, (d[2] - d[0]) * (d[3] - d[1]))
            for i, d in enumerate(detections)
        ]
        areas.sort(key=lambda t: -t[1])
        order = [i for i, _ in areas]

        keep = [True] * len(detections)

        for i_pos, big_idx in enumerate(order):
            if not keep[big_idx]:
                continue
            big = detections[big_idx]
            bx1, by1, bx2, by2 = big[0], big[1], big[2], big[3]

            for small_idx in order[i_pos + 1:]:
                if not keep[small_idx]:
                    continue
                small = detections[small_idx]
                sx1, sy1, sx2, sy2 = small[0], small[1], small[2], small[3]

                # Intersection
                ix1 = max(bx1, sx1)
                iy1 = max(by1, sy1)
                ix2 = min(bx2, sx2)
                iy2 = min(by2, sy2)
                if ix2 <= ix1 or iy2 <= iy1:
                    continue
                inter = (ix2 - ix1) * (iy2 - iy1)
                small_area = (sx2 - sx1) * (sy2 - sy1)
                if small_area <= 0:
                    keep[small_idx] = False
                    continue

                if inter / small_area >= threshold:
                    keep[small_idx] = False

        return [d for i, d in enumerate(detections) if keep[i]]
