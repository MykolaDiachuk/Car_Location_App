# Temporal smoothing

YOLO occasionally misses a car on one frame and finds it again on the
next. On a static parking lot that flicker is the dominant source of
"Cars: 14 → 13 → 14" jitter in the live counter.

Parking Monitor ships an optional **K-of-N hysteresis with carry-over**
that absorbs those one-off misses without introducing more than a few
seconds of lag.

Source: [`parking/tracker.py`](../parking/tracker.py) (`SpotStateTracker`).

---

## Enabling it

It's on by default. To disable, set in `.env`:

```env
TEMPORAL_SMOOTH_ENABLED=false
```

Tuning knobs (with defaults):

```env
TEMPORAL_SMOOTH_ENABLED=true
TEMPORAL_WINDOW_N=5            # rolling window size in frames
TEMPORAL_MIN_K=3               # min frames a bbox must appear in to survive
TEMPORAL_IOU_MATCH=0.3         # IoU threshold for matching bboxes across frames
TEMPORAL_MAX_AGE_SECONDS=10.0  # drop history entries older than this
```

---

## How it works

On every frame the tracker keeps a rolling window of the last **N** frames
of YOLO detections. It clusters bboxes across the entire window by IoU.
Any cluster that appears in at least **K** distinct frames is emitted as a
single detection — using the **most recent sighting's position**. Clusters
whose latest sighting wasn't the current frame are **carried over** from
history, hiding the YOLO miss.

```
Frame:        1   2   3   4   5   6
YOLO sees:    ✓   ✓   ✓   ✓   ✗   ✓
Tracker emits ✓   ✓   ✓   ✓   ✓   ✓
                              └── carry-over: cluster has 4 sightings in last 5 frames
```

Two warm-up safeguards prevent cold-start / idle-wake false-empty reports:

1. **Pass-through while the window holds fewer than `min_k` frames** —
   the first few frames after start emit raw detections, no filtering.
2. **Time-aware aging** — entries older than `TEMPORAL_MAX_AGE_SECONDS`
   (default 10 s) are dropped on every `update()`, so a long idle gap
   auto-clears the window.

The API server additionally calls `tracker.reset()` on idle→active
transitions and before heartbeat snapshots so the first frame after a wake
is never voted down by stale history.

---

## Trade-offs

| Behaviour | Cost |
|---|---|
| **Appearance lag** | A newly-arrived car must be seen K times before it's reported. |
| **Departure lag** | After a car leaves, its bbox persists for up to `N − K + 1` more frames before falling out of the window. |
| **Warm-up** | First `K − 1` frames after startup (and after idle wake-up) are pass-through, so no false "0 cars". |

At the defaults (N=5, K=3) on `ANALYSIS_INTERVAL=1.0`, both lags are
≈ 3 seconds. Perfectly acceptable for a parking lot, would be terrible
for autonomous driving.

---

## Picking K and N

A useful starting point is N=5, K=3. Tune from there:

| Symptom | Try |
|---|---|
| Stable detections still drop in/out by ±1 | Lower K (e.g. N=10, K=5) — current value too strict |
| Phantom cars appearing for 1–2 frames | Raise K (e.g. N=7, K=5) |
| New cars take too long to appear | Lower K |
| Cars stay in the report long after leaving | Lower N |

**Important constraint:** `TEMPORAL_MAX_AGE_SECONDS` must be
`≥ TEMPORAL_WINDOW_N × ANALYSIS_INTERVAL × 1.5`. If it's too tight, frames
at the back of the window get aged out before they can be counted and the
K-of-N condition becomes unsatisfiable (the tracker would emit nothing).

---

## What this does NOT fix

The "Free" counter can still flicker even when "Cars" is stable. Free
spots come from a separate grid-scan over the BEV mask in
`ParkingAnalyzer._find_free_spots()` — that step doesn't pass through the
tracker, so small bbox jitter on occupied cars still shifts where free
cells fit. Stabilising the free-spot scan is a separate enhancement on the
backlog.
