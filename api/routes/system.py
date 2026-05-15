"""GET /api/v1/system — host CPU/RAM/disk/network/temperature metrics.

Powers the system-resources panel in the web dashboard. Returns the latest
sample plus a rolling history buffer maintained by
:mod:`api.system_stats`.
"""
from __future__ import annotations

from fastapi import APIRouter

from api.system_stats import collector as _sys_collector

router = APIRouter()


@router.get("/system")
def get_system_stats() -> dict:
    """Return current host metrics, server info, and recent history."""
    return {
        "server": _sys_collector.get_server_info(),
        "current": _sys_collector.collect(),
        "history": _sys_collector.get_history(),
    }
