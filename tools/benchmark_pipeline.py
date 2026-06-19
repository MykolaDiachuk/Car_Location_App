"""Benchmark per-stage processing time of the parking pipeline.

Measures the same stages that appear in the thesis performance table:
  1. YOLO inference + postprocessing (model.predict + box extraction)
  2. IoSmaller dedupe + temporal smoothing
  3. BEV perspective transform (cv2.warpPerspective)
  4. Grid scan for free spots (with integral images)
  5. Full pipeline cycle

Usage:
    python tools/benchmark_pipeline.py
    python tools/benchmark_pipeline.py --image tools/input/frame_20260511_105517.jpg
    python tools/benchmark_pipeline.py --iterations 50 --warmup 5
    python tools/benchmark_pipeline.py --camera        # grab one frame via RTSP
    python tools/benchmark_pipeline.py --csv results.csv

The frame source priority is:
    --image PATH  >  --camera  >  most recent file in tools/input/

Output: a console table identical in structure to the thesis table plus
percentile detail, and (optionally) a CSV with per-iteration timings.
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR.parent))

from config import ParkingConfig
from parking.analyzer import ParkingAnalyzer
from parking.detector import VehicleDetector
from parking.tracker import SpotStateTracker
from parking.transformer import PerspectiveTransformer

INPUT_DIR = TOOLS_DIR / "input"

STAGE_LABELS = {
    "yolo": "YOLO inference + postprocessing",
    "smoothing": "IoSmaller dedupe + temporal smoothing",
    "bev": "BEV warpPerspective",
    "grid_scan": "Grid scan for free spots",
    "total": "Full pipeline cycle",
}


@dataclass
class StageTimings:
    """Per-iteration millisecond samples for each pipeline stage."""

    samples: dict[str, list[float]] = field(
        default_factory=lambda: {k: [] for k in STAGE_LABELS}
    )

    def record(self, stage: str, ms: float) -> None:
        self.samples[stage].append(ms)

    def summary(self, stage: str) -> dict[str, float]:
        data = self.samples[stage]
        if not data:
            return {"mean": 0.0, "median": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0, "n": 0}
        return {
            "mean": statistics.fmean(data),
            "median": statistics.median(data),
            "p95": _percentile(data, 95),
            "min": min(data),
            "max": max(data),
            "n": len(data),
        }


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return s[lo] + (s[hi] - s[lo]) * frac


def _pick_default_frame() -> Path | None:
    """Return the most recently modified file under tools/input/, if any."""
    if not INPUT_DIR.exists():
        return None
    candidates = [p for p in INPUT_DIR.iterdir() if p.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _grab_camera_frame(url: str) -> np.ndarray:
    print(f"Connecting to camera: {url}")
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        raise RuntimeError("Could not connect to camera")
    for _ in range(5):  # warm-up
        cap.read()
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise RuntimeError("Failed to read frame from camera")
    return frame


def _load_frame(args: argparse.Namespace, config: ParkingConfig) -> np.ndarray:
    if args.image:
        path = Path(args.image)
        if not path.exists():
            raise FileNotFoundError(path)
        frame = cv2.imread(str(path))
        if frame is None:
            raise RuntimeError(f"OpenCV could not decode {path}")
        print(f"Frame source: image {path}")
        return frame

    if args.camera:
        if not config.CAMERA_URL:
            raise RuntimeError("CAMERA_URL is not configured")
        frame = _grab_camera_frame(config.CAMERA_URL)
        print(f"Frame source: live camera ({frame.shape[1]}x{frame.shape[0]})")
        return frame

    default = _pick_default_frame()
    if default is None:
        raise RuntimeError(
            "No frame supplied. Pass --image PATH, --camera, or place a "
            "frame under tools/input/."
        )
    frame = cv2.imread(str(default))
    if frame is None:
        raise RuntimeError(f"OpenCV could not decode {default}")
    print(f"Frame source: most-recent {default}")
    return frame


def _raw_yolo_detect(detector: VehicleDetector, frame: np.ndarray) -> list[np.ndarray]:
    """YOLO inference + box extraction WITHOUT the IoSmaller dedupe step."""
    results = detector.model.predict(
        source=frame,
        conf=detector.conf,
        classes=detector.classes,
        verbose=False,
    )
    detections: list[np.ndarray] = []
    if len(results) > 0:
        for box in results[0].boxes:
            coords = box.xyxy[0].cpu().numpy()
            conf = box.conf[0].cpu().numpy()
            detections.append(np.append(coords, conf))
    return detections


def _bench_iteration(
    frame: np.ndarray,
    detector: VehicleDetector,
    transformer: PerspectiveTransformer,
    analyzer: ParkingAnalyzer,
    tracker: SpotStateTracker | None,
    timings: StageTimings,
) -> None:
    """Run all stages once, recording per-stage and total ms."""
    t_total_start = time.perf_counter()

    # 1) YOLO inference + post-processing
    t0 = time.perf_counter()
    raw_detections = _raw_yolo_detect(detector, frame)
    yolo_ms = (time.perf_counter() - t0) * 1000.0

    # 2) IoSmaller dedupe + temporal smoothing
    t0 = time.perf_counter()
    deduped = VehicleDetector._dedupe_overlapping(raw_detections, detector.overlap_threshold)
    if tracker is not None:
        detections = tracker.update(deduped)
    else:
        detections = deduped
    smoothing_ms = (time.perf_counter() - t0) * 1000.0

    # 3) BEV perspective transform
    t0 = time.perf_counter()
    bev_view = transformer.transform(frame)
    bev_ms = (time.perf_counter() - t0) * 1000.0

    # 4) Grid scan for free spots — replicates the body of analyzer.analyze()
    #    up to and including _find_free_spots(); the per-spot drawing and the
    #    ParkingState assembly are O(N) bookkeeping and are intentionally
    #    excluded so the number reflects the scan algorithm itself.
    occupied_points = []
    for det in detections:
        x1, y1, x2, y2 = map(int, det[:4])
        ax = x2 if analyzer.anchor == "bottom_right" else (x1 + x2) // 2
        px, py = transformer.transform_point(ax, y2)
        px = max(0, min(analyzer.bev_w - 1, px))
        py = max(0, min(analyzer.bev_h - 1, py))
        o = analyzer._orientation_for_det(x1, y1, x2, y2, transformer)
        occupied_points.append((px, py, o))

    t0 = time.perf_counter()
    temp_mask = analyzer._mark_occupied(analyzer.parking_mask.copy(), occupied_points)
    _free = analyzer._find_free_spots(temp_mask)
    grid_ms = (time.perf_counter() - t0) * 1000.0

    total_ms = (time.perf_counter() - t_total_start) * 1000.0

    timings.record("yolo", yolo_ms)
    timings.record("smoothing", smoothing_ms)
    timings.record("bev", bev_ms)
    timings.record("grid_scan", grid_ms)
    timings.record("total", total_ms)


def _print_table(timings: StageTimings) -> None:
    name_w = max(len(v) for v in STAGE_LABELS.values()) + 2
    header = f"{'Stage':<{name_w}}{'Mean':>10}{'Median':>10}{'p95':>10}{'Min':>10}{'Max':>10}{'N':>6}"
    sep = "-" * len(header)
    print()
    print(sep)
    print(header)
    print(sep)
    for key, label in STAGE_LABELS.items():
        s = timings.summary(key)
        print(
            f"{label:<{name_w}}"
            f"{s['mean']:>10.1f}"
            f"{s['median']:>10.1f}"
            f"{s['p95']:>10.1f}"
            f"{s['min']:>10.1f}"
            f"{s['max']:>10.1f}"
            f"{s['n']:>6}"
        )
    print(sep)
    print("All values in milliseconds. p95 = 95th percentile.")


def _write_csv(path: Path, timings: StageTimings) -> None:
    keys = list(STAGE_LABELS.keys())
    n_rows = max(len(timings.samples[k]) for k in keys)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["iteration"] + [STAGE_LABELS[k] + " (ms)" for k in keys])
        for i in range(n_rows):
            row = [i + 1]
            for k in keys:
                vals = timings.samples[k]
                row.append(f"{vals[i]:.3f}" if i < len(vals) else "")
            writer.writerow(row)
    print(f"Per-iteration timings written to: {path}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark per-stage processing time of the parking pipeline."
    )
    parser.add_argument(
        "--image", type=str, default=None,
        help="Path to an input frame (jpg/png). If omitted, uses --camera "
             "or the most recent file in tools/input/.",
    )
    parser.add_argument(
        "--camera", action="store_true",
        help="Grab one frame from the configured RTSP camera and use it.",
    )
    parser.add_argument(
        "--iterations", type=int, default=20,
        help="Number of measured iterations (default: 20).",
    )
    parser.add_argument(
        "--warmup", type=int, default=3,
        help="Warm-up iterations excluded from stats (default: 3). "
             "Important for fair YOLO timing — the first call loads weights.",
    )
    parser.add_argument(
        "--csv", type=str, default=None,
        help="Optional path to dump per-iteration timings as CSV.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config = ParkingConfig()
    frame = _load_frame(args, config)

    print(f"Frame shape: {frame.shape[1]}x{frame.shape[0]}")
    print(f"YOLO weights: {config.MODEL_PATH}")
    print(f"BEV canvas: {config.BEV_WIDTH}x{config.BEV_HEIGHT}, "
          f"grid step={config.CHECK_STEP}")
    print(f"Temporal smoothing: "
          f"{'ON' if config.TEMPORAL_SMOOTH_ENABLED else 'OFF'} "
          f"(N={config.TEMPORAL_WINDOW_N}, K={config.TEMPORAL_MIN_K})")

    print("Initialising pipeline components...")
    detector = VehicleDetector(config)
    transformer = PerspectiveTransformer(config)
    analyzer = ParkingAnalyzer(config)
    tracker = (
        SpotStateTracker.from_config(config)
        if config.TEMPORAL_SMOOTH_ENABLED
        else None
    )

    print(f"Warm-up: {args.warmup} iter, measured: {args.iterations} iter")

    # Warm-up — YOLO's first predict() loads weights into RAM/GPU and the
    # first warpPerspective call allocates caches. Excluding these gives a
    # fair steady-state measurement.
    warmup_sink = StageTimings()
    for i in range(args.warmup):
        _bench_iteration(frame, detector, transformer, analyzer, tracker, warmup_sink)
        print(f"  warm-up {i + 1}/{args.warmup}: "
              f"total {warmup_sink.samples['total'][-1]:.1f} ms")

    # Measured run
    timings = StageTimings()
    for i in range(args.iterations):
        _bench_iteration(frame, detector, transformer, analyzer, tracker, timings)
        print(f"  iter {i + 1}/{args.iterations}: "
              f"total {timings.samples['total'][-1]:.1f} ms")

    _print_table(timings)

    if args.csv:
        _write_csv(Path(args.csv), timings)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())