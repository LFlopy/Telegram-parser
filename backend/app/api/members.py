from __future__ import annotations

import csv
import io
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from backend.app.db.repositories import TaskRepository, TaskResultRepository, UserRecord
from backend.app.db.session import Database
from backend.app.schemas.members import MemberListResponse, MemberResponse
from backend.app.tasks.manager import TaskManagerError

router = APIRouter(prefix="/api/tasks/{task_id}", tags=["members"])
CSV_PAGE_SIZE = 1000
CSV_HEADERS = (
    "telegram_user_id",
    "username",
    "first_name",
    "last_name",
    "is_bot",
)


def member_response(member: UserRecord) -> MemberResponse:
    return MemberResponse(
        telegram_user_id=member.telegram_user_id,
        username=member.username,
        first_name=member.first_name,
        last_name=member.last_name,
        is_bot=member.is_bot,
    )


async def require_task(database: Database, task_id: UUID) -> None:
    async with database.session() as session:
        if await TaskRepository(session).get(task_id) is None:
            raise TaskManagerError("task_not_found", "Задача не найдена.", 404)


@router.get("/members", response_model=MemberListResponse)
async def list_task_members(
    task_id: UUID,
    request: Request,
    search: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> MemberListResponse:
    database: Database = request.app.state.database
    await require_task(database, task_id)
    async with database.session() as session:
        members, total = await TaskResultRepository(session).list_members(
            task_id,
            search=search,
            page=page,
            page_size=page_size,
        )
    return MemberListResponse(
        items=[member_response(member) for member in members],
        total=total,
        page=page,
        page_size=page_size,
    )


def safe_csv_value(value: str | None) -> str:
    if value is None:
        return ""
    if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value


def csv_chunk(rows: list[UserRecord], *, include_header: bool) -> str:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    if include_header:
        writer.writerow(CSV_HEADERS)
    for member in rows:
        writer.writerow(
            (
                member.telegram_user_id,
                safe_csv_value(member.username),
                safe_csv_value(member.first_name),
                safe_csv_value(member.last_name),
                "true" if member.is_bot else "false",
            )
        )
    return stream.getvalue()


async def stream_task_csv(database: Database, task_id: UUID) -> AsyncIterator[str]:
    page = 1
    yield "\ufeff" + csv_chunk([], include_header=True)
    while True:
        async with database.session() as session:
            rows, _ = await TaskResultRepository(session).list_members(
                task_id,
                search=None,
                page=page,
                page_size=CSV_PAGE_SIZE,
            )
        if not rows:
            break
        yield csv_chunk(rows, include_header=False)
        if len(rows) < CSV_PAGE_SIZE:
            break
        page += 1


@router.get("/export.csv")
async def export_task_members(task_id: UUID, request: Request) -> StreamingResponse:
    database: Database = request.app.state.database
    await require_task(database, task_id)
    return StreamingResponse(
        stream_task_csv(database, task_id),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="telegram-members-{task_id}.csv"',
            "X-Content-Type-Options": "nosniff",
        },
    )
