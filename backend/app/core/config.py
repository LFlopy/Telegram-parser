"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

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


def _local_host(value: str) -> str:
    host = value.strip()
    if host.casefold() == "localhost":
        return host
    try:
        if ip_address(host).is_loopback:
            return host
    except ValueError:
        pass
    raise ValueError("TELEGRAM_MANAGER_HOST must be a loopback address")


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise ValueError("TELEGRAM_MANAGER_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("TELEGRAM_MANAGER_PORT must be between 1 and 65535")
    return port


def _local_origin(value: str) -> str:
    origin = value.strip().rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("CORS origins must be plain http(s) origins")
    _local_host(parsed.hostname)
    return origin


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
    version: str = "0.1.0"
    log_level: str = field(default="INFO")


def load_settings() -> Settings:
    origins_raw = _env(
        "TELEGRAM_MANAGER_CORS_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    )
    origins = tuple(_local_origin(o) for o in origins_raw.split(",") if o.strip())
    return Settings(
        host=_local_host(_env("TELEGRAM_MANAGER_HOST", "127.0.0.1")),
        port=_port(_env("TELEGRAM_MANAGER_PORT", "8000")),
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
