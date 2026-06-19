# Parking Configurator

A local web tool for the one-time setup of the parking monitoring system.
You run it on your laptop before deploying: connect the camera, calibrate
the image, paint the masks and draw the map — and you get an archive with
ready-to-use files to drop into the main project.

---

## How to run

You need **Python 3.10+** and access to the RTSP camera you'll be using.

```bash
cd parking_configurator
pip install -e .
python -m parking_configurator
```

The browser opens automatically at `http://127.0.0.1:8765`. If it doesn't,
open it manually.

To start from scratch (wipe the previous session):

```bash
python -m parking_configurator --fresh
```

---

## How it works

The interface has 4 steps in the left sidebar. Steps unlock as you complete
the previous ones. Everything you do is **saved automatically** — you can
close the tab in the middle of the work and come back later.

### 1. Camera

Connect the camera's RTSP stream:

- **Builder**: pick a manufacturer from the list (Hikvision, Dahua, Axis,
  Reolink, TP-Link Tapo, ONVIF, or a custom path). Enter the IP, port,
  username and password — the correct URL is assembled for you.
- **Manual URL**: paste a complete RTSP string.

Click **Test connection** to make sure the camera responds. Then
**Capture frame** — this saves one frame for the following steps.

> If the test fails: check the port in the camera settings (usually 554 or
> 5554), make sure the username/password are correct, and that the camera
> is reachable from your laptop on the network.

### 2. BEV calibration

Now you tell the system **which area of the image it analyzes**. Drag the 4
colored points on the photo so they bound the parking rectangle (as if you
were looking at it from above):

- 🟢 **TL** — top-left corner of the lot
- 🔵 **TR** — top-right
- 🔴 **BR** — bottom-right
- 🟡 **BL** — bottom-left

The points can be **outside the frame** — that's fine (if the lot is
clipped by the edge of the photo). The "top-down" view (Bird's Eye View)
appears immediately on the right — make sure it looks like a rectangular
parking lot.

`BEV Width × BEV Height` is the size of the resulting "top-down" view in
pixels. The default 1200×800 works for most cases.

Click **Save BEV** to unlock the next steps.

### 3. Masks and map (any order)

Here you draw on top of the BEV. **The drawings are semi-transparent** —
the photo shows through so you can orient yourself. On export only the
masks remain, without the photo.

**Useful actions everywhere:**

- `Ctrl + mouse wheel` — zoom in on a region (like in graphics editors)
- `Ctrl + LMB` or `middle mouse button` — pan
- `Clear` — reset to the starting state

#### 3a. Parking mask

You draw where parking **is** allowed and where it **isn't** (lawn, exit,
sidewalk).

- **LMB** — green (allowed)
- **RMB** — red (forbidden)
- On export, green becomes white and red becomes black

The starting state is **everything allowed** (green). It's usually easier
to just paint the forbidden zones with RMB.

#### 3b. Orientation mask

This tells the system **how cars are parked** in different parts of the lot.

- **LMB** — green (parallel parking, cars side-on to the lane)
- **RMB** — blue (perpendicular, cars parked tail-in)
- **Eraser** — remove a zone

The starting state is nothing marked. You don't have to paint the whole
map, only the zones where orientation matters.

#### 3c. Parking map

This is a **visual** outline of the lot/section boundaries for later use in
the frontend. It does **not affect** detection — this step is optional.

- **Add** mode: click — new polygon vertex, `Enter` or double-click —
  close the polygon, `Esc` — cancel
- **Edit** mode: drag a vertex, `Shift+click` on an edge — insert a new
  vertex, `Delete` — remove

Clicks outside the BEV bounds (outside the blue frame) are not allowed.

### 4. Export

Review the checklist (what's done, what isn't) and click **Download ZIP**.
You'll get a `parking_config.zip` with everything you need.

---

## How to use the result

The simplest path is the script in the main project, which unpacks the
archive and merges the `.env` for you:

```bash
python scripts/apply_config.py path/to/parking_config.zip
```

Add `--dry-run` to preview the changes without writing anything. The
script:

- replaces only the keys in your `.env` that are present in the bundle
  (other comments/variables are left untouched),
- places the masks/SVG into `assets/`,
- prints a list of what changed.

**Or by hand:** unzip `parking_config.zip` into the root of the main
repository — the files land in the right places:

```
parking_config.zip
├── .env                              ← camera and BEV configuration
└── assets/
    ├── parking_mask.png              ← allowed-zones mask
    ├── orientation_zones.png         ← orientation mask
    └── parking_map.svg               ← map (for the frontend, optional)
```

If you already have a `.env`, merge `CAMERA_URL`, `SRC_POINTS`,
`BEV_WIDTH`, `BEV_HEIGHT` into your file by hand.

Run the main program (`python monitor.py` or `docker compose up`) — it
picks up the new settings automatically. No edits to `config.py` are
needed: every variable from `.env` takes priority over the defaults.

---

## FAQ

**Can I close the tab and come back?**
Yes. Progress is saved to disk automatically in the
`.parking_configurator_cache/` directory (it appears wherever you launch
from). On the next start there's a "Start from scratch" button at the top
if you want to reset.

**Which port does it run on?**
`8765` by default. To change it: `python -m parking_configurator --port 9000`.

**Can I run it without a browser?**
Yes: `python -m parking_configurator --no-browser` — then open the page
yourself.

**Is it local-only, or can I deploy it?**
Local only. This is a **one-time setup tool** to run before deploying the
main system, not a service for continuous use.

**Can I reconfigure the lot later?**
Yes. Run `python -m parking_configurator` again and redo the steps (you can
start with `--fresh` to avoid confusion with old data), download a new ZIP
and replace the files in the project.
