from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from backend.app.schemas.groups import (
    GroupAccessResponse,
    GroupListResponse,
    GroupResolveRequest,
    GroupResponse,
)
from backend.app.telegram.group_service import (
    GroupInfo,
    TelegramGroupService,
)

router = APIRouter(prefix="/api/groups", tags=["groups"])


def get_group_service(request: Request) -> TelegramGroupService:
    return request.app.state.telegram_group_service


GroupServiceDependency = Annotated[
    TelegramGroupService, Depends(get_group_service)
]


def _group_response(group: GroupInfo) -> GroupResponse:
    return GroupResponse(
        id=group.id,
        telegram_group_id=group.telegram_group_id,
        title=group.title,
        username=group.username,
        group_type=group.group_type,
        access_state=group.access_state,
    )


@router.get("", response_model=GroupListResponse)
async def list_groups(
    service: GroupServiceDependency,
    search: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> GroupListResponse:
    result = await service.get_page(
        search=search,
        page=page,
        page_size=page_size,
    )
    return GroupListResponse(
        items=[_group_response(group) for group in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post("/resolve", response_model=GroupResponse)
async def resolve_group(
    payload: GroupResolveRequest,
    service: GroupServiceDependency,
) -> GroupResponse:
    group = await service.resolve_public(payload.link_or_username)
    return _group_response(group)


@router.get("/{group_id}/access", response_model=GroupAccessResponse)
async def check_group_access(
    group_id: int,
    service: GroupServiceDependency,
) -> GroupAccessResponse:
    access = await service.check_access(group_id)
    return GroupAccessResponse(
        can_read_members=access.can_read_members,
        reason=access.reason,
    )
