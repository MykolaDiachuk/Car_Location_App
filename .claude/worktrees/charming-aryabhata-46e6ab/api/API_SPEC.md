# Parking Monitor — API Specification

Base URL (local): `http://localhost:8000`

All responses are JSON unless noted otherwise. No authentication required (local network only).

---

## Endpoints

### `GET /api/config`

Returns static dimensions of the Bird's Eye View (BEV) canvas. Call once on page load to avoid hardcoding these values.

**Response `200`**
```json
{
  "bev_width":  1200,
  "bev_height": 800,
  "car_width":  150,
  "car_height": 80
}
```

| Field | Type | Description |
|---|---|---|
| `bev_width` | `int` | BEV canvas width in pixels |
| `bev_height` | `int` | BEV canvas height in pixels |
| `car_width` | `int` | Typical car footprint width in BEV pixels |
| `car_height` | `int` | Typical car footprint height in BEV pixels |

---

### `GET /api/state`

Returns the latest parking lot snapshot. Updates every ~1 second on the server side.

**Response `200`**
```json
{
  "timestamp":        "2026-04-13T09:15:42.123456Z",
  "total_spots":      22,
  "occupied":         3,
  "free":             19,
  "occupancy_percent": 13.6,
  "spots": [
    {
      "status":      "occupied",
      "orientation": "perpendicular",
      "center_bev":  { "x": 0.48, "y": 0.55 },
      "bbox_bev":    { "x1": 501, "y1": 400, "x2": 651, "y2": 480 },
      "confidence":  0.91
    },
    {
      "status":      "free",
      "orientation": "parallel",
      "center_bev":  { "x": 0.25, "y": 0.67 },
      "bbox_bev":    { "x1": 225, "y1": 496, "x2": 375, "y2": 576 },
      "confidence":  1.0
    }
  ]
}
```

**Top-level fields**

| Field | Type | Description |
|---|---|---|
| `timestamp` | `string` (ISO-8601 UTC) | When this snapshot was captured |
| `total_spots` | `int` | Total spots detected this frame |
| `occupied` | `int` | Spots with a vehicle |
| `free` | `int` | Spots without a vehicle |
| `occupancy_percent` | `float` (0–100) | `occupied / total_spots * 100` |
| `spots` | `ParkingSpot[]` | Per-spot details (see below) |

**`ParkingSpot` object**

| Field | Type | Description |
|---|---|---|
| `status` | `"free"` \| `"occupied"` | Current occupancy |
| `orientation` | `"parallel"` \| `"perpendicular"` | How the spot is oriented relative to the driving lane |
| `center_bev.x` | `float` (0–1) | Horizontal center, normalized. Multiply by `bev_width` for pixel position. |
| `center_bev.y` | `float` (0–1) | Vertical center, normalized. Multiply by `bev_height` for pixel position. |
| `bbox_bev.x1` | `int` | Left edge in BEV pixels |
| `bbox_bev.y1` | `int` | Top edge in BEV pixels |
| `bbox_bev.x2` | `int` | Right edge in BEV pixels |
| `bbox_bev.y2` | `int` | Bottom edge in BEV pixels |
| `confidence` | `float` (0–1) | Detection confidence. Free spots inferred by algorithm have `1.0`. |

> **Coordinate system:** origin `(0, 0)` is the top-left corner of the BEV canvas.  
> `bbox_bev` values are in absolute BEV pixels and can be used directly as SVG `<rect>` attributes  
> (i.e. `x=x1`, `y=y1`, `width=x2-x1`, `height=y2-y1`) when the SVG `viewBox` is `"0 0 {bev_width} {bev_height}"`.

**Response `503`** — server is starting up, pipeline not yet initialized
```json
{ "detail": "No data yet — pipeline still initializing" }
```

---

### `GET /parking_map.svg`

Returns the SVG floor plan of the parking lot.

**Response `200`** — `Content-Type: image/svg+xml`  
The SVG uses `viewBox="0 0 1200 800"` (same coordinate space as `bbox_bev`).  
Embed inline and overlay spot rectangles on top using an SVG layer with the same `viewBox`.

**Response `404`** — map file not yet generated
```json
{ "detail": "SVG map not available yet" }
```

---

## Polling recommendation

Poll `GET /api/state` every **2–3 seconds**. The server updates the state every ~1 second; polling faster than that wastes resources without benefit.

Use `timestamp` to detect unchanged frames and skip re-rendering:
```js
if (state.timestamp !== lastTimestamp) {
  lastTimestamp = state.timestamp;
  // re-render spots
}
```

---

## Rendering spots on the SVG map

Recommended approach — two SVG layers with the same `viewBox`:

```html
<!-- Layer 1: parking lot floor plan -->
<svg viewBox="0 0 1200 800" style="position:absolute;inset:0;width:100%;height:100%">
  <!-- inline content of parking_map.svg -->
</svg>

<!-- Layer 2: occupancy overlay (rendered by JS) -->
<svg viewBox="0 0 1200 800" style="position:absolute;inset:0;width:100%;height:100%;pointer-events:none">
  <!-- one <rect> per spot from /api/state -->
</svg>
```

Each spot as a `<rect>`:
```js
// state.spots[i]
const { x1, y1, x2, y2 } = spot.bbox_bev;
const color = spot.status === "occupied" ? "#f04040" : "#30d060";

// <rect x="x1" y="y1" width="x2-x1" height="y2-y1" fill="color" fill-opacity="0.55" stroke="color" stroke-width="2" rx="4"/>
```

---

## Not yet implemented

| Feature | Notes |
|---|---|
| WebSocket live push | Currently polling only. A future `/ws/state` endpoint would push on every new frame. |
| Historical data | No persistence; only the latest frame is available. |
| Multi-camera | Single camera only. `camera_id` field not yet in the response. |
