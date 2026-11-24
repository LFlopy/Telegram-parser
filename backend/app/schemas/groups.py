from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GroupResponse(BaseModel):
    id: int
    telegram_group_id: int
    title: str
    username: str | None
    group_type: Literal["group", "supergroup"]
    access_state: Literal["unknown", "available", "no_access"]


class GroupListResponse(BaseModel):
    items: list[GroupResponse]
    total: int
    page: int
    page_size: int


class GroupResolveRequest(BaseModel):
    link_or_username: str = Field(min_length=1, max_length=128)


class GroupAccessResponse(BaseModel):
    can_read_members: bool | None
    reason: str | None
