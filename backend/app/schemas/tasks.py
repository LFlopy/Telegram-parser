from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


TaskStatusValue = Literal[
    "pending", "running", "waiting", "completed", "cancelled", "failed"
]


class ParseTaskRequest(BaseModel):
    group_id: int


class TaskResponse(BaseModel):
    id: UUID
    group_id: int
    group_title: str
    status: TaskStatusValue
    processed_count: int
    saved_count: int
    skipped_count: int
    error_count: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None


class TaskListResponse(BaseModel):
    items: list[TaskResponse]
    total: int
    page: int
    page_size: int
