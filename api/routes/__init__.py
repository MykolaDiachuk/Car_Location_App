"""HTTP route modules for the Parking Monitor API.

Each module declares an ``APIRouter`` exposing one logical endpoint group:

- :mod:`state`   — ``GET /api/v1/state``    (also marks client activity)
- :mod:`health`  — ``GET /api/v1/health``   (operational status, no activity)
- :mod:`history` — ``GET /api/v1/history``  (historical occupancy for charts)
- :mod:`system`  — ``GET /api/v1/system``   (host CPU/RAM/disk/network metrics)
- :mod:`index`   — ``GET /``                (API discovery / version info)

Routers are imported and mounted in :mod:`api.server`.
"""
