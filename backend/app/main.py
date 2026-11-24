"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from backend.app.api import auth, groups, system, tasks
from backend.app.core.config import settings
from backend.app.db.migrations import upgrade_database
from backend.app.db.session import Database
from backend.app.telegram.group_service import GroupServiceError, TelegramGroupService
from backend.app.telegram.participant_collector import ParticipantCollector
from backend.app.telegram.session_manager import AuthFlowError, TelegramSessionManager
from backend.app.tasks.manager import TaskManager, TaskManagerError

logger = logging.getLogger("telegram_manager")


def create_app(
    frontend_dist: Path | None = None,
    session_manager: TelegramSessionManager | None = None,
    group_service: TelegramGroupService | None = None,
    database: Database | None = None,
    task_manager: TaskManager | None = None,
) -> FastAPI:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    telegram_manager = session_manager or TelegramSessionManager(settings.data_dir)
    telegram_groups = group_service or TelegramGroupService(telegram_manager)
    application_database = database or Database(settings.database_url)
    application_tasks = task_manager or TaskManager(
        application_database,
        ParticipantCollector(telegram_manager, telegram_groups),
        telegram_manager,
        telegram_groups,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        upgrade_database(application_database.url)
        application.state.database = application_database
        application.state.task_manager = application_tasks
        application.state.telegram_session_manager = telegram_manager
        application.state.telegram_group_service = telegram_groups
        application.state.local_origins = local_origins
        await application_tasks.initialize()
        await telegram_manager.restore()
        try:
            yield
        finally:
            await application_tasks.close()
            await telegram_manager.close()
            await application_database.close()

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        docs_url="/api/docs" if settings.debug else None,
        openapi_url="/api/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )

    @app.exception_handler(AuthFlowError)
    async def auth_error_handler(
        request: Request, exc: AuthFlowError
    ) -> JSONResponse:
        headers = (
            {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "Проверьте формат введённых данных.",
            },
        )

    @app.exception_handler(GroupServiceError)
    async def group_error_handler(
        request: Request, exc: GroupServiceError
    ) -> JSONResponse:
        headers = (
            {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
            headers=headers,
        )

    @app.exception_handler(TaskManagerError)
    async def task_error_handler(
        request: Request, exc: TaskManagerError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    local_origins = {
        *settings.cors_origins,
        f"http://127.0.0.1:{settings.port}",
        f"http://localhost:{settings.port}",
    }

    @app.middleware("http")
    async def protect_local_api(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        origin = request.headers.get("origin")
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and origin is not None
            and origin not in local_origins
        ):
            return JSONResponse(
                status_code=403,
                content={
                    "code": "origin_forbidden",
                    "message": "Источник запроса не разрешён.",
                },
            )
        return await call_next(request)

    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(groups.router)
    app.include_router(tasks.router)
    app.include_router(tasks.ws_router)

    configured_dist = frontend_dist or settings.frontend_dist
    dist: Path | None = configured_dist.resolve() if configured_dist.is_dir() else None
    index_file = dist / "index.html" if dist else None
    if index_file and index_file.is_file():
        active_dist = dist
        assert active_dist is not None
        assets_dir = active_dist / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str) -> FileResponse:
            route_root = full_path.partition("/")[0]
            if route_root in {"api", "ws"}:
                raise HTTPException(status_code=404, detail="Not found")

            candidate = (active_dist / full_path).resolve()
            try:
                candidate.relative_to(active_dist)
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
