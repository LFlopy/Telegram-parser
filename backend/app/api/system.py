"""System endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from backend.app.core.config import settings

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "name": settings.app_name,
        "version": settings.version,
        "time": datetime.now(UTC).isoformat(),
    }
