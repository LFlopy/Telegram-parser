from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def synchronous_database_url(url: str) -> str:
    return url.replace("sqlite+aiosqlite://", "sqlite://", 1)


def upgrade_database(url: str) -> None:
    database_path = make_url(url).database
    if database_path and database_path != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "backend/app/db/migrations"))
    config.set_main_option("sqlalchemy.url", synchronous_database_url(url))
    command.upgrade(config, "head")
