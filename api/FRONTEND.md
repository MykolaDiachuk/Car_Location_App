# Frontend Integration Guide

## Quick start (mock mode)

```bash
MOCK_MODE=true uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload
```

Occupancy cycles every second — no camera or YOLO needed.

---

## Key endpoints

| Endpoint | Notes |
|---|---|
| `GET /api/v1/state` | Main data endpoint. **Must poll to keep pipeline alive** — camera releases after 30 s of silence. |
| `GET /api/v1/health` | Status only, does **not** wake the pipeline. Safe for monitoring dashboards. |

---

## Polling

Poll `/api/v1/state` every **2 seconds**. Handle `503` as a cold-start signal — keep polling, don't treat it as an error.

```ts
const id = setInterval(async () => {
  const res = await fetch("/api/v1/state");
  if (res.ok) onUpdate(await res.json());
}, 2000);
```

Pause polling when the tab is hidden (`visibilitychange`) to avoid keeping the pipeline alive needlessly.

---

## Pipeline states

| `pipeline_status` | Show |
|---|---|
| `"running"` | Live data |
| `"idle"` / `"starting"` | "Connecting…" spinner |
| `"error"` | "Camera offline", keep last known data |

`stale: true` (snapshot > 10 s old) → subtle "data may be outdated" indicator.

---

## Coordinates

- `center_bev` — normalized `{x, y}` in `[0, 1]`. Multiply by canvas size to place markers.
- `bbox_bev` — BEV pixels. Scale using `bev_width` / `bev_height` from the response.

---

## Aggregates

Pre-computed — no need to count spots yourself:

```ts
const { total_spots, occupied, free, occupancy_percent } = state;
```

---

## Spot IDs

`spot.id` is **not stable** across frames. Use a derived key for React:

```ts
const key = `${s.center_bev.x.toFixed(2)}_${s.center_bev.y.toFixed(2)}`;
```
