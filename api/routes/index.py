"""GET / — API discovery endpoint.

Returns the server name, version, and links to the main endpoints and
documentation. Useful for sanity-checking that the server is up.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def root() -> dict:
    """Return API index with endpoint links."""
    return {
        "name": "Parking Monitor API",
        "version": "1.0.0",
        "endpoints": {
            "state": "/api/v1/state",
            "health": "/api/v1/health",
            "history": "/api/v1/history",
            "system": "/api/v1/system",
            "docs": "/docs",
            "ui": "/web/",
        },
    }
