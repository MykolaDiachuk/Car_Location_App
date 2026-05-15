# Calibration

The default `config.py` ships with `SRC_POINTS` and the two mask PNGs
calibrated for **one specific camera** — the one the maintainer runs. To
deploy on a different camera you have to redo the calibration.

> **Note:** The calibration utilities in `tools/` and the GUI
> [`parking_configurator/`](../parking_configurator/) are kept in the repo
> for reference but are **owner-only** — they are not part of the public
> contract, may change without notice, and are not covered by
> documentation beyond this page.

---

## Workflow

For a brand-new camera you'll do these five steps once, in order.

### 1. Capture a frame

Save one still from the live feed to disk so the next tools can work with
it offline.

```bash
python tools/capture_frame.py
```

Writes to `tools/input/`.

### 2. Find the BEV source points

Interactive UI: click four corners of the parking quad in the captured
frame, in the order Top-Left → Top-Right → Bottom-Right → Bottom-Left.

```bash
python tools/find_bev_points.py
```

Copy the resulting `SRC_POINTS` array into `config.py`. Values can be
negative or outside the frame — that's normal when the camera is mounted
on a wall and looks down at an angle.

### 3. Verify the BEV

Generate a static BEV image to sanity-check the transform:

```bash
python tools/generate_bev.py
```

Painted parking spaces should look roughly rectangular and aligned. If the
output looks distorted, redo step 2.

### 4. Paint the parking mask

White = parking allowed, black = forbidden (flowerbeds, exits, driveways,
no-parking zones).

```bash
python tools/edit_parking_mask.py
```

Saves to `assets/parking_mask.png`.

### 5. Paint the orientation zones

Where cars park **parallel** to the camera (green) vs. **perpendicular**
(blue). Used to draw spot rectangles in the right orientation.

```bash
python tools/edit_orientation_zones.py
```

Saves to `assets/orientation_zones.png`.

---

## GUI alternative

The PyQt5 app at [`parking_configurator/`](../parking_configurator/)
bundles steps 1–5 into a single 5-tab desktop application with live
previews. Owner-only, requires `pip install -r parking_configurator/requirements.txt`.

```bash
python parking_configurator/main.py
```

---

## Sanity checking your calibration

After editing `config.py` and the masks:

```bash
python tools/test_bev_camera.py   # live BEV preview from the RTSP stream
python monitor.py                 # full pipeline in an OpenCV window
```

If cars are detected but mapped to the wrong BEV positions, revisit
`SRC_POINTS` or `DETECTION_ANCHOR` (see
[configuration.md](configuration.md)).

If detections vanish near the lot boundary, repaint
`assets/parking_mask.png` to widen the allowed region.
