# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

Real-time parking lot occupancy monitoring using YOLOv11 vehicle detection and Bird's Eye View (BEV) perspective transformation. Designed for unstructured parking lots without lane markings.

## Commands

```bash
# Install backend dependencies
pip install -r requirements.txt

# Install configurator dependencies (separate environment recommended)
pip install -r parking_configurator/requirements.txt

# Run real-time monitor (main application)
python monitor.py

# Run GUI setup tool
python parking_configurator/main.py

# Calibration tools (run individually as needed — owner use only)
python tools/capture_frame.py              # Grab frame from RTSP camera
python tools/test_connection.py            # Test RTSP connectivity
python tools/find_bev_points.py            # Interactive SRC_POINTS selector
python tools/generate_bev.py               # Generate static BEV image
python tools/edit_parking_mask.py          # Paint allowed/forbidden zones
python tools/edit_orientation_zones.py     # Paint parallel/perpendicular zones
python tools/test_bev_camera.py            # Live BEV preview
```

No formal test suite exists. Manual testing is done via `tools/test_connection.py` and visual inspection of `monitor.py` output.

> **`tools/` and `parking_configurator/` are owner-only.** Do not read or modify files in these directories unless explicitly asked.

## Architecture

Three independent components share `config.py` as the central configuration source.

### 1. Backend Pipeline (`parking/`)

**Data flow:**
```
Camera Frame (RTSP)
  → VehicleDetector (YOLO11n) → list of [x1,y1,x2,y2,confidence]
  → PerspectiveTransformer (homography) → BEV image + projected points
  → ParkingAnalyzer (mask-based grid scan) → annotated image + ParkingState
```

- `parking/detector.py` — wraps Ultralytics YOLO; filters by `VEHICLE_CLASSES` and `CONF_THRESHOLD`
- `parking/transformer.py` — computes homography from `SRC_POINTS` → BEV corners; `transform_point()` returns `None` if outside bounds
- `parking/analyzer.py` — loads `parking_mask.png` and `orientation_zones.png`; marks occupied areas using car dimensions, then grid-scans remaining white pixels for free spots
- `parking/pipeline.py` — `ParkingPipeline.process_frame()` orchestrates the three above; returns `AnalysisResult` (bev view, annotated view, `ParkingState`)
- `parking/models.py` — Pydantic models: `ParkingSpot`, `ParkingState`, `SpotStatus`, `SpotOrientation`, `NormalizedPoint`
- `monitor.py` — RTSP connection with retry, runs pipeline on a configurable interval, displays result in OpenCV window (`q`=quit, `s`=save screenshot)

### 2. Static Assets (`assets/`)

- `parking_mask.png` — grayscale: white = parking allowed, black = forbidden (flowerbeds, exits, etc.)
- `orientation_zones.png` — color-coded: green = parallel spots, blue = perpendicular spots

These are consumed by `ParkingAnalyzer` at startup. Edit them with the tools or the configurator.

### 3. Parking Configurator (`parking_configurator/`) — owner-only

> **Do not read or modify files in `parking_configurator/` or `tools/` unless explicitly asked.** These directories are for the owner's personal use and manual testing only — they are not part of the core backend and should be treated as off-limits by default.



PyQt5 GUI with 5 tabs driven by a shared `AppState` dataclass (`app/state.py`). Tabs are in `app/tabs/`:
- `camera.py` — RTSP URL builder, live preview, frame capture
- `bev.py` — drag 4 corner points to set `SRC_POINTS`, live BEV preview
- `paint_mask.py` — reusable brush widget used by both mask and zone tabs
- `map_builder.py` — place/resize/rotate spots and borders, exports `parking_map.svg` and `spots.json`

`app/window.py` (`MainWindow`) owns the `QTabWidget` and passes `AppState` to all tabs.

### 4. Configuration (`config.py`)

All settings live in the `ParkingConfig` class. Key values to know when debugging:

| Setting | Purpose |
|---|---|
| `SRC_POINTS` | 4 camera points defining the BEV quad (can be negative/outside frame) |
| `BEV_WIDTH`, `BEV_HEIGHT` | Output BEV canvas size (default 1200×800) |
| `CAR_WIDTH`, `CAR_HEIGHT` | Constant car footprint in BEV pixels (150×80) — no perspective correction |
| `CHECK_STEP` | Grid scan stride for free spot detection (default 20px) |
| `CAMERA_URL` | RTSP connection string |
| `VEHICLE_CLASSES` | YOLO class IDs: `[2, 3, 5, 7]` = car, motorcycle, bus, truck |

### Calibration Workflow

When setting up a new camera location, follow this sequence:
1. `capture_frame.py` → saves frame to `tools/input/`
2. `find_bev_points.py` → copy resulting `SRC_POINTS` into `config.py`
3. `generate_bev.py` → verify BEV looks correct
4. `edit_parking_mask.py` → paint and save `assets/parking_mask.png`
5. `edit_orientation_zones.py` → paint and save `assets/orientation_zones.png`

Or use the Configurator GUI for an integrated workflow.

## Known Issues

- **Spot count flicker** — grid-scan finds slightly different free spots each frame; no temporal hysteresis yet
- **Fixed car size** — `CAR_WIDTH/CAR_HEIGHT` constants don't account for perspective depth variation
- **No API** — `ParkingState` is JSON-ready (Pydantic) but no HTTP/WebSocket endpoint is wired up
- **Configurator map not persisted** — closing the window loses all placed spots/borders (no save/load)
- **`tools/` duplicates configurator** — both have mask painters; `tools/` scripts are CLI-only alternatives
