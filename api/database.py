"""SQLite storage for parking occupancy history.

The database file lives at DB_PATH (env var, default /data/parking_history.db).
A Docker bind-mount keeps it alive across container re-deploys on the
Raspberry Pi host.

Thread safety: each thread gets its own connection via thread-local storage.
WAL journal mode allows concurrent reads (API) and writes (pipeline worker).
"""

import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from parking.models import ParkingState

logger = logging.getLogger(__name__)

_DB_PATH: str = ""
_local = threading.local()

# ── Connection management ────────────────────────────────────────────────────

_SQLITE_TS_FMT = "%Y-%m-%d %H:%M:%S"


def _get_conn() -> sqlite3.Connection:
    """One connection per thread (sqlite3 connections are not thread-safe)."""
    conn: sqlite3.Connection | None = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(_DB_PATH, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return conn


# ── Initialization ───────────────────────────────────────────────────────────


def init_db(db_path: str) -> None:
    """Create the database file, table, and index if they don't exist."""
    global _DB_PATH
    _DB_PATH = db_path

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = _get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS parking_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT    NOT NULL,
            total_spots     INTEGER NOT NULL,
            occupied        INTEGER NOT NULL,
            free            INTEGER NOT NULL,
            occupancy_percent REAL  NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_snapshots_ts
            ON parking_snapshots(timestamp);
        """
    )
    conn.commit()
    logger.info("Database initialized at %s", db_path)


# ── Write ────────────────────────────────────────────────────────────────────


def record_snapshot(state: ParkingState) -> None:
    """Insert one occupancy snapshot row."""
    conn = _get_conn()
    ts_str = state.timestamp.astimezone(timezone.utc).strftime(_SQLITE_TS_FMT)
    conn.execute(
        """INSERT INTO parking_snapshots
               (timestamp, total_spots, occupied, free, occupancy_percent)
           VALUES (?, ?, ?, ?, ?)""",
        (ts_str, state.total_spots, state.occupied, state.free, state.occupancy_percent),
    )
    conn.commit()


# ── Read ─────────────────────────────────────────────────────────────────────


def _auto_bucket_seconds(from_dt: datetime, to_dt: datetime) -> int:
    """Pick aggregation granularity so the response has ~120-360 points."""
    span = (to_dt - from_dt).total_seconds()
    if span <= 3_600:          # <= 1 h  -> raw
        return 0
    if span <= 6 * 3_600:      # <= 6 h  -> 1 min
        return 60
    if span <= 86_400:          # <= 24 h -> 5 min
        return 300
    if span <= 7 * 86_400:     # <= 7 d  -> 30 min
        return 1_800
    return 7_200               # > 7 d   -> 2 h


def query_history(
    from_dt: datetime,
    to_dt: datetime,
    bucket_seconds: int | None = None,
) -> tuple[list[dict], int]:
    """Return occupancy history between two UTC datetimes.

    Returns (rows, bucket_seconds_used).
    Each row: {timestamp, total_spots, occupied, free, occupancy_percent}.
    """
    if bucket_seconds is None:
        bucket_seconds = _auto_bucket_seconds(from_dt, to_dt)

    conn = _get_conn()
    from_str = from_dt.astimezone(timezone.utc).strftime(_SQLITE_TS_FMT)
    to_str = to_dt.astimezone(timezone.utc).strftime(_SQLITE_TS_FMT)

    if bucket_seconds == 0:
        rows = conn.execute(
            """SELECT timestamp, total_spots, occupied, free, occupancy_percent
               FROM parking_snapshots
               WHERE timestamp >= ? AND timestamp < ?
               ORDER BY timestamp""",
            (from_str, to_str),
        ).fetchall()
        return [dict(r) for r in rows], 0

    # Aggregated: bucket by integer-dividing the unix timestamp
    sql = (
        "SELECT"
        "    datetime("
        "        (CAST(strftime('%s', timestamp) AS INTEGER) / ?) * ?,"
        "        'unixepoch'"
        "    ) AS timestamp,"
        "    CAST(ROUND(AVG(total_spots)) AS INTEGER) AS total_spots,"
        "    CAST(ROUND(AVG(occupied))    AS INTEGER) AS occupied,"
        "    CAST(ROUND(AVG(free))        AS INTEGER) AS free,"
        "    ROUND(AVG(occupancy_percent), 1)         AS occupancy_percent"
        " FROM parking_snapshots"
        " WHERE timestamp >= ? AND timestamp < ?"
        " GROUP BY 1"
        " ORDER BY 1"
    )
    rows = conn.execute(
        sql, (bucket_seconds, bucket_seconds, from_str, to_str)
    ).fetchall()
    return [dict(r) for r in rows], bucket_seconds


# ── Maintenance ──────────────────────────────────────────────────────────────


def cleanup_old_data(retention_days: int) -> int:
    """Delete snapshots older than *retention_days*. Returns rows deleted."""
    conn = _get_conn()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).strftime(
        _SQLITE_TS_FMT
    )
    cursor = conn.execute(
        "DELETE FROM parking_snapshots WHERE timestamp < ?", (cutoff,)
    )
    conn.commit()
    deleted = cursor.rowcount
    if deleted:
        logger.info("Cleaned up %d snapshots older than %d days", deleted, retention_days)
    return deleted


def get_snapshot_count() -> int:
    """Total stored snapshots (for health / debug)."""
    conn = _get_conn()
    row = conn.execute("SELECT COUNT(*) FROM parking_snapshots").fetchone()
    return row[0] if row else 0
