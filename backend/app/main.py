"""FastAPI application factory."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api import system
from backend.app.core.config import settings

logger = logging.getLogger("telegram_manager")


def create_app(frontend_dist: Path | None = None) -> FastAPI:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        docs_url="/api/docs" if settings.debug else None,
        openapi_url="/api/openapi.json" if settings.debug else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(system.router)

    configured_dist = frontend_dist or settings.frontend_dist
    dist: Path | None = configured_dist.resolve() if configured_dist.is_dir() else None
    index_file = dist / "index.html" if dist else None
    if index_file and index_file.is_file():
        assets_dir = dist / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str) -> FileResponse:
            route_root = full_path.partition("/")[0]
            if route_root in {"api", "ws"}:
                raise HTTPException(status_code=404, detail="Not found")

            candidate = (dist / full_path).resolve()
            try:
                candidate.relative_to(dist)
            except ValueError:
                raise HTTPException(status_code=404, detail="Not found") from None

            return FileResponse(candidate if full_path and candidate.is_file() else index_file)

    logger.info(
        "Telegram Manager started (host=%s port=%s, frontend_dist=%s)",
        settings.host,
        settings.port,
        "yes" if index_file else "not found",
    )
    return app


app = create_app()
