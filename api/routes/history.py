"""GET /api/v1/history — historical occupancy for chart rendering.

Provide either ``period`` (e.g. ``24h``, ``7d``) or an explicit
``from``/``to`` ISO 8601 range. Aggregation granularity is selected
automatically so the response contains ~120–360 points regardless of the
requested span.

This endpoint does NOT mark client activity — fetching history will not
wake an idle pipeline.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from parking.models import HistoryPoint, HistoryResponse
from api.database import query_history

router = APIRouter()

_PERIOD_RE = re.compile(r"^(\d+)([hd])$")
_MAX_QUERY_DAYS = 90


def _parse_period(raw: str) -> timedelta:
    """Parse a ``<int><h|d>`` lookback window. Raises ValueError on bad input."""
    m = _PERIOD_RE.match(raw.strip().lower())
    if not m:
        raise ValueError(
            f"Invalid period '{raw}'. Use <number>h or <number>d, e.g. 24h, 7d."
        )
    value, unit = int(m.group(1)), m.group(2)
    if unit == "h":
        return timedelta(hours=value)
    return timedelta(days=value)


def _ensure_utc(dt: datetime) -> datetime:
    """Tag naive datetimes as UTC; pass aware datetimes through unchanged."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("/history", response_model=HistoryResponse)
def get_history(
    period: str | None = Query(
        None,
        description=(
            "Lookback window, e.g. 1h, 6h, 24h, 7d, 30d. "
            "Mutually exclusive with from/to."
        ),
        examples=["1h", "6h", "24h", "7d", "30d"],
    ),
    from_dt: datetime | None = Query(
        None,
        alias="from",
        description="Start of time range (ISO 8601 UTC).",
    ),
    to_dt: datetime | None = Query(
        None,
        alias="to",
        description="End of time range (ISO 8601 UTC). Defaults to now.",
    ),
) -> HistoryResponse:
    """Return historical occupancy data for chart rendering."""
    now = datetime.now(timezone.utc)

    # ── resolve time range ──
    if period and from_dt:
        raise HTTPException(400, "Provide either 'period' or 'from'/'to', not both.")

    if period:
        try:
            delta = _parse_period(period)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        qto = now
        qfrom = now - delta
    elif from_dt:
        qfrom = _ensure_utc(from_dt)
        qto = _ensure_utc(to_dt) if to_dt else now
    else:
        # Default: last 24 hours
        qto = now
        qfrom = now - timedelta(hours=24)

    # ── validate ──
    if qfrom >= qto:
        raise HTTPException(400, "'from' must be before 'to'.")
    if (qto - qfrom).days > _MAX_QUERY_DAYS:
        raise HTTPException(400, f"Maximum query range is {_MAX_QUERY_DAYS} days.")

    # ── query ──
    rows, bucket = query_history(qfrom, qto)
    points = [
        HistoryPoint(
            # DB stores naive UTC strings — tag with timezone so JSON output
            # includes 'Z' and the frontend parses them correctly.
            timestamp=datetime.strptime(r["timestamp"], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            ),
            total_spots=int(r["total_spots"]),
            occupied=int(r["occupied"]),
            free=int(r["free"]),
            occupancy_percent=float(r["occupancy_percent"]),
        )
        for r in rows
    ]

    return HistoryResponse(
        period_from=qfrom,
        period_to=qto,
        bucket_seconds=bucket,
        points=points,
    )
