"""Temporal hysteresis for vehicle detections — with carry-over from history.

Keeps a rolling window of the last N frames' detections. On each `update()`
the tracker clusters bboxes ACROSS the entire window (not just the current
frame): every detection from every recorded frame is assigned to the cluster
whose existing bboxes it overlaps with by IoU >= `iou_match`, or starts a
new cluster if none matches. A cluster that spans at least `min_k` distinct
frames is emitted as a single output bbox — using its **most recent**
position so that any slight YOLO drift over time is honored.

The key difference from a plain "filter current-frame detections" approach
is **carry-over**: if a cluster has K confirmations in the window, it is
emitted EVEN when YOLO didn't see the car on the current frame. That hides
single-frame YOLO misses, which is the main visible flicker source for a
static parking lot.

Trade-offs of carry-over:

  * Appearance lag: a newly-arrived car must be seen K times before it
    surfaces in the output (same as the no-carry version).
  * Departure lag: once a car leaves, its cluster stays in the window for
    up to N - K + 1 more frames before its match-count drops below K. At
    ANALYSIS_INTERVAL=1s with N=5, K=3 that's ~2-3 seconds — acceptable
    for parking.
  * False-positive resistance: same as before; a phantom bbox needs to
    appear in K frames to be emitted.

Two warm-up safeguards prevent "cold start shows zero cars" surprises:

  1. **Pass-through during warm-up.** While the window holds fewer than
     `min_k` frames, the tracker returns the current frame's detections
     untouched. K-of-N filtering only kicks in once there's enough history
     to vote against.

  2. **Time-aware aging.** Each frame stored in history carries a timestamp.
     Before clustering, entries older than `max_age_seconds` are dropped.
     This means after an idle wake-up (e.g. pipeline slept for an hour),
     the stale history evaporates and the tracker behaves as if it just
     started — first frame after wake passes through unfiltered.
"""
from __future__ import annotations

import time
from collections import deque
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from config import ParkingConfig


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    """Standard IoU on [x1, y1, x2, y2, ...] arrays."""
    ax1, ay1, ax2, ay2 = float(a[0]), float(a[1]), float(a[2]), float(a[3])
    bx1, by1, bx2, by2 = float(b[0]), float(b[1]), float(b[2]), float(b[3])

    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0

    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = max(0.0, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(0.0, (bx2 - bx1) * (by2 - by1))
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return inter / union


class SpotStateTracker:
    """K-of-N hysteresis with cross-frame clustering and carry-over emission.

    Algorithm (update one frame):
      1. Age out: drop history entries older than `max_age_seconds`.
      2. Append the current frame (timestamp + detections) to the window.
      3. If the window now has fewer than `min_k` frames → return detections
         AS-IS (warm-up: not enough history to vote yet).
      4. Cluster every bbox in the window: a new detection joins an existing
         cluster if it overlaps any of that cluster's bboxes by IoU >=
         `iou_match`, otherwise starts a new cluster.
      5. For each cluster spanning >= `min_k` distinct frames: emit one
         bbox using the most recent (latest frame_idx) sighting's position
         and the mean confidence across the cluster's sightings.

    This emits carry-over detections even when YOLO missed the car on the
    current frame — that's the whole point: hide single-frame misses.
    """

    def __init__(
        self,
        window_n: int,
        min_k: int,
        iou_match: float,
        max_age_seconds: float = 10.0,
    ) -> None:
        if window_n < 1:
            raise ValueError(f"window_n must be >= 1, got {window_n}")
        if not (1 <= min_k <= window_n):
            raise ValueError(
                f"min_k must be in [1, window_n={window_n}], got {min_k}"
            )
        if max_age_seconds <= 0:
            raise ValueError(
                f"max_age_seconds must be > 0, got {max_age_seconds}"
            )
        self.window_n = window_n
        self.min_k = min_k
        self.iou_match = float(iou_match)
        self.max_age_seconds = float(max_age_seconds)
        # Each entry: (timestamp_seconds, list_of_detection_arrays)
        self._history: deque[tuple[float, list[np.ndarray]]] = deque(maxlen=window_n)

    @classmethod
    def from_config(cls, config: "ParkingConfig") -> "SpotStateTracker":
        return cls(
            window_n=int(getattr(config, "TEMPORAL_WINDOW_N", 5)),
            min_k=int(getattr(config, "TEMPORAL_MIN_K", 3)),
            iou_match=float(getattr(config, "TEMPORAL_IOU_MATCH", 0.3)),
            max_age_seconds=float(getattr(config, "TEMPORAL_MAX_AGE_SECONDS", 10.0)),
        )

    def reset(self) -> None:
        """Drop all history. Call explicitly after long pauses (e.g. idle-wake)
        if you don't want to rely on max_age_seconds alone."""
        self._history.clear()

    def _drop_expired(self, now: float) -> None:
        """Pop entries older than `max_age_seconds` from the front."""
        while self._history and (now - self._history[0][0]) > self.max_age_seconds:
            self._history.popleft()

    def update(self, detections: list[np.ndarray]) -> list[np.ndarray]:
        """Filter + carry-over detections through the temporal window.

        During warm-up (window has fewer than min_k frames after aging) the
        input list is returned unchanged. Once warmed up, the tracker emits
        every cluster of bboxes that spans >= min_k distinct frames in the
        window — INCLUDING clusters whose most recent sighting was a frame
        ago (carry-over), so single-frame YOLO misses are hidden.
        """
        now = time.time()

        # Step 1: age out stale history (handles idle wake-up automatically)
        self._drop_expired(now)

        # Step 2: record current frame
        self._history.append((now, list(detections)))

        # Step 3: warm-up pass-through — not enough history to vote against
        if len(self._history) < self.min_k:
            return list(detections)

        # Step 4: cluster bboxes ACROSS the whole window.
        # Each cluster is a list of (frame_idx, det_array) tuples.
        # A new det attaches to a cluster if it overlaps ANY existing bbox
        # in that cluster by IoU >= iou_match — this is robust to small
        # YOLO drift over time.
        clusters: list[list[tuple[int, np.ndarray]]] = []
        for frame_idx, (_ts, frame_dets) in enumerate(self._history):
            for det in frame_dets:
                attached = False
                for cluster in clusters:
                    matched = False
                    for _existing_idx, existing_det in cluster:
                        if _iou(det, existing_det) >= self.iou_match:
                            matched = True
                            break
                    if matched:
                        cluster.append((frame_idx, det))
                        attached = True
                        break
                if not attached:
                    clusters.append([(frame_idx, det)])

        # Step 5: emit clusters that span >= min_k distinct frames, using
        # the most recent sighting's position and the mean confidence.
        survivors: list[np.ndarray] = []
        for cluster in clusters:
            distinct_frames = {f_idx for f_idx, _ in cluster}
            if len(distinct_frames) < self.min_k:
                continue

            # Latest sighting (highest frame_idx) drives the position
            latest_frame_idx, latest_det = max(cluster, key=lambda t: t[0])
            confs = [
                float(d[4]) for _f, d in cluster if len(d) >= 5
            ]
            avg_conf = (
                sum(confs) / len(confs)
                if confs
                else (float(latest_det[4]) if len(latest_det) >= 5 else 1.0)
            )

            survivors.append(np.array([
                float(latest_det[0]),
                float(latest_det[1]),
                float(latest_det[2]),
                float(latest_det[3]),
                float(avg_conf),
            ], dtype=np.float32))

        return survivors
