from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect

from backend.app.schemas.tasks import ParseTaskRequest, TaskListResponse, TaskResponse
from backend.app.tasks.manager import TaskManager, TaskManagerError, TaskSnapshot

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
ws_router = APIRouter(tags=["tasks"])


def get_task_manager(request: Request) -> TaskManager:
    return request.app.state.task_manager


TaskManagerDependency = Annotated[TaskManager, Depends(get_task_manager)]


def task_response(task: TaskSnapshot) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        group_id=task.group_id,
        group_title=task.group_title,
        status=task.status.value,
        processed_count=task.processed_count,
        saved_count=task.saved_count,
        skipped_count=task.skipped_count,
        error_count=task.error_count,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        error_code=task.error_code,
        error_message=task.error_message,
    )


@router.post("/parse", response_model=TaskResponse, status_code=202)
async def start_parse(
    payload: ParseTaskRequest, manager: TaskManagerDependency
) -> TaskResponse:
    return task_response(await manager.start(payload.group_id))


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    manager: TaskManagerDependency,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> TaskListResponse:
    items, total = await manager.list(page=page, page_size=page_size)
    return TaskListResponse(
        items=[task_response(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: UUID, manager: TaskManagerDependency) -> TaskResponse:
    task = await manager.get(task_id)
    if task is None:
        raise TaskManagerError("task_not_found", "Задача не найдена.", 404)
    return task_response(task)


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(task_id: UUID, manager: TaskManagerDependency) -> TaskResponse:
    return task_response(await manager.cancel(task_id))


@ws_router.websocket("/ws/tasks")
async def task_events(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    allowed_origins: set[str] = websocket.app.state.local_origins
    if origin is not None and origin not in allowed_origins:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    manager: TaskManager = websocket.app.state.task_manager
    try:
        async with manager.subscribe() as queue:
            while True:
                snapshot = await queue.get()
                await websocket.send_json(
                    task_response(snapshot).model_dump(mode="json")
                )
    except WebSocketDisconnect:
        return
