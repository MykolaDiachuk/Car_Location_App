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

    def detect(self, frame: np.ndarray) -> list[np.ndarray]:
        """Detect vehicles in frame.
        
        Returns:
            List of detections, each as [x1, y1, x2, y2, confidence].
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
        return detections
