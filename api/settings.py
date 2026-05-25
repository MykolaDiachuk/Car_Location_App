"""Runtime settings for the Parking Monitor API server.

All environment variables consumed by the HTTP layer are parsed here exactly
once at startup and frozen into a ``Settings`` dataclass. Routes, the
background worker, and ``server.py`` itself read these values via
``request.app.state.settings`` — no module-level ``os.getenv`` calls are
scattered through the rest of the package.

For a description of every variable, see ``docs/configuration.md``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Default DB location for bare-metal / Windows / macOS deployments. Docker
# users override this to /data/parking_history.db via the DB_PATH env var so
# the bind-mount at /data persists across container redeploys.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB_PATH = str(_PROJECT_ROOT / "data" / "parking_history.db")


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _env_origins(name: str, default: str = "*") -> list[str]:
    raw = os.getenv(name, default).strip()
    if raw == "*" or not raw:
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


@dataclass(frozen=True)
class Settings:
    """Immutable HTTP-layer configuration.

    Built once from environment variables in :meth:`Settings.from_env`.
    """

    # Pipeline behaviour
    analysis_interval: float = 1.0
    idle_timeout: float = 30.0
    stale_threshold: float = 10.0
    heartbeat_interval: float = 3600.0  # 0 disables heartbeat snapshots

    # Database — defaults to <project_root>/data/parking_history.db for
    # bare-metal use. Docker users override via DB_PATH=/data/parking_history.db.
    db_path: str = _DEFAULT_DB_PATH
    record_interval: float = 120.0
    retention_days: int = 90

    # HTTP
    cors_origins: list[str] = field(default_factory=lambda: ["*"])

    # Camera reconnect strategy (constants — not env-driven)
    reconnect_backoff_initial: float = 1.0
    reconnect_backoff_max: float = 30.0
    heartbeat_warmup_frames: int = 3

    @classmethod
    def from_env(cls) -> "Settings":
        """Build a Settings instance from process environment variables."""
        return cls(
            analysis_interval=_env_float("ANALYSIS_INTERVAL", 1.0),
            idle_timeout=_env_float("IDLE_TIMEOUT", 30.0),
            stale_threshold=_env_float("STALE_THRESHOLD", 10.0),
            heartbeat_interval=_env_float("HEARTBEAT_INTERVAL", 3600.0),
            db_path=os.getenv("DB_PATH", _DEFAULT_DB_PATH),
            record_interval=_env_float("RECORD_INTERVAL", 120.0),
            retention_days=_env_int("RETENTION_DAYS", 90),
            cors_origins=_env_origins("CORS_ORIGINS"),
        )

    def heartbeat_summary(self) -> str:
        """Human-readable heartbeat status for startup logs."""
        return f"{self.heartbeat_interval}s" if self.heartbeat_interval > 0 else "disabled"
