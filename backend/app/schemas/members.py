from __future__ import annotations

from pydantic import BaseModel


class MemberResponse(BaseModel):
    telegram_user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    is_bot: bool


class MemberListResponse(BaseModel):
    items: list[MemberResponse]
    total: int
    page: int
    page_size: int
