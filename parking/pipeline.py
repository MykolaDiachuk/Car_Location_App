"""Parking analysis pipeline."""
from dataclasses import dataclass
from typing import TYPE_CHECKING
import numpy as np

from parking.detector import VehicleDetector
from parking.transformer import PerspectiveTransformer
from parking.analyzer import ParkingAnalyzer
from parking.tracker import SpotStateTracker
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

        # Optional temporal hysteresis (K-of-N over last N frames). Lives
        # between detector and analyzer so the analyzer's "find free spots
        # in NOT-occupied area" logic operates on already-stabilised cars.
        if getattr(config, "TEMPORAL_SMOOTH_ENABLED", False):
            self.tracker: SpotStateTracker | None = SpotStateTracker.from_config(config)
        else:
            self.tracker = None

    def process_frame(self, frame: np.ndarray) -> AnalysisResult:
        """Run detection, BEV transform, and occupancy analysis on a frame."""
        detections = self.detector.detect(frame)
        if self.tracker is not None:
            detections = self.tracker.update(detections)
        bev_view = self.transformer.transform(frame)
        analysis_view, state = self.analyzer.analyze(
            bev_view, detections, self.transformer
        )
        return AnalysisResult(
            bev_view=bev_view,
            analysis_view=analysis_view,
            state=state,
        )
