"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Project root: repo/telegram-manager (parent of backend/)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


def _sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Runtime settings. All values come from the environment (no secrets defaults)."""

    host: str
    port: int
    cors_origins: tuple[str, ...]
    data_dir: Path
    frontend_dist: Path
    database_url: str
    debug: bool
    app_name: str = "Telegram Manager"
    version: str = "0.0.1"
    log_level: str = field(default="INFO")


def load_settings() -> Settings:
    origins_raw = _env(
        "TELEGRAM_MANAGER_CORS_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    )
    origins = tuple(o.strip() for o in origins_raw.split(",") if o.strip())
    return Settings(
        host=_env("TELEGRAM_MANAGER_HOST", "127.0.0.1"),
        port=int(_env("TELEGRAM_MANAGER_PORT", "8000")),
        cors_origins=origins,
        data_dir=Path(_env("TELEGRAM_MANAGER_DATA_DIR", str(DATA_DIR))),
        frontend_dist=Path(_env("TELEGRAM_MANAGER_FRONTEND_DIST", str(FRONTEND_DIST))),
        database_url=_env(
            "TELEGRAM_MANAGER_DATABASE_URL",
            _sqlite_url(Path(_env("TELEGRAM_MANAGER_DATA_DIR", str(DATA_DIR))) / "app.db"),
        ),
        debug=_env_bool("TELEGRAM_MANAGER_DEBUG", False),
        log_level=_env("TELEGRAM_MANAGER_LOG_LEVEL", "INFO").upper(),
    )


settings = load_settings()
