"""Parking analysis pipeline."""
from dataclasses import dataclass
from typing import TYPE_CHECKING
import numpy as np

from parking.detector import VehicleDetector
from parking.transformer import PerspectiveTransformer
from parking.analyzer import ParkingAnalyzer
from parking.models import ParkingState

if TYPE_CHECKING:
    from config import ParkingConfig


@dataclass
class AnalysisResult:
    """Result of a single frame analysis."""
    bev_view: np.ndarray
    analysis_view: np.ndarray
    state: ParkingState


class ParkingPipeline:
    """Processes camera frames through the full parking analysis pipeline."""

    def __init__(self, config: "ParkingConfig") -> None:
        self.detector = VehicleDetector(config)
        self.transformer = PerspectiveTransformer(config)
        self.analyzer = ParkingAnalyzer(config)

    def process_frame(self, frame: np.ndarray) -> AnalysisResult:
        """Run detection, BEV transform, and occupancy analysis on a frame."""
        detections = self.detector.detect(frame)
        bev_view = self.transformer.transform(frame)
        analysis_view, state = self.analyzer.analyze(
            bev_view, detections, self.transformer
        )
        return AnalysisResult(
            bev_view=bev_view,
            analysis_view=analysis_view,
            state=state,
        )
