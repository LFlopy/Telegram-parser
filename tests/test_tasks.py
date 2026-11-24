from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.db.migrations import upgrade_database
from backend.app.db.models import GroupMember, TaskMember, TaskStatus, TelegramUser
from backend.app.db.session import Database
from backend.app.main import create_app
from backend.app.telegram.group_service import GroupInfo
from backend.app.telegram.participant_collector import CollectorError, ParticipantRecord
from backend.app.telegram.session_manager import AccountInfo, TelegramSessionManager
from backend.app.tasks.manager import TaskManager, TaskManagerError


def database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


class FakeSessionManager:
    async def status(self) -> AccountInfo:
        return AccountInfo(1, "Owner", "owner")


class FakeGroupService:
    async def get_group(self, group_id: int) -> GroupInfo:
        return GroupInfo(
            id=group_id,
            telegram_group_id=group_id,
            title="Test group",
            username="test_group",
            group_type="supergroup",
            access_state="available",
        )


class SequenceCollector:
    def __init__(self, runs: list[list[ParticipantRecord] | CollectorError]) -> None:
        self.runs = runs
        self.calls = 0

    async def collect(self, group_id: int) -> AsyncIterator[ParticipantRecord]:
        run = self.runs[min(self.calls, len(self.runs) - 1)]
        self.calls += 1
        if isinstance(run, CollectorError):
            raise run
        for record in run:
            await asyncio.sleep(0)
            yield record


class BlockingCollector:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def collect(self, group_id: int) -> AsyncIterator[ParticipantRecord]:
        yield ParticipantRecord(101, "first", "First", None, False)
        self.started.set()
        await asyncio.Event().wait()
        if False:
            yield ParticipantRecord(0, None, None, None, False)


async def wait_finished(manager: TaskManager, task_id: UUID) -> None:
    for _ in range(200):
        task = await manager.get(task_id)
        if task is not None and task.status not in {
            TaskStatus.PENDING,
            TaskStatus.RUNNING,
            TaskStatus.WAITING,
        }:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("task did not finish")


def records() -> list[ParticipantRecord]:
    return [
        ParticipantRecord(101, "first", "First", None, False),
        ParticipantRecord(102, None, "Second", "User", False),
    ]


@pytest.mark.asyncio
async def test_task_manager_batches_and_deduplicates_repeated_collection(
    tmp_path: Path,
) -> None:
    url = database_url(tmp_path / "tasks.db")
    upgrade_database(url)
    database = Database(url)
    collector = SequenceCollector([records(), records()])
    manager = TaskManager(
        database, collector, FakeSessionManager(), FakeGroupService(), batch_size=1
    )
    await manager.initialize()

    first = await manager.start(-1001)
    await wait_finished(manager, first.id)
    second = await manager.start(-1001)
    await wait_finished(manager, second.id)

    first_result = await manager.get(first.id)
    second_result = await manager.get(second.id)
    assert first_result is not None and first_result.status is TaskStatus.COMPLETED
    assert second_result is not None and second_result.status is TaskStatus.COMPLETED
    assert first_result.saved_count == second_result.saved_count == 2
    async with database.session() as session:
        assert await session.scalar(select(func.count()).select_from(TelegramUser)) == 2
        assert await session.scalar(select(func.count()).select_from(GroupMember)) == 2
        assert await session.scalar(select(func.count()).select_from(TaskMember)) == 4
    await database.close()


@pytest.mark.asyncio
async def test_task_manager_cancels_and_limits_active_task(tmp_path: Path) -> None:
    url = database_url(tmp_path / "cancel.db")
    upgrade_database(url)
    database = Database(url)
    collector = BlockingCollector()
    manager = TaskManager(
        database, collector, FakeSessionManager(), FakeGroupService(), batch_size=1
    )
    await manager.initialize()
    task = await manager.start(-1001)
    await collector.started.wait()

    with pytest.raises(TaskManagerError) as conflict:
        await manager.start(-1001)
    assert conflict.value.code == "task_already_running"

    cancelled = await manager.cancel(task.id)
    assert cancelled.status is TaskStatus.CANCELLED
    assert cancelled.saved_count == 1
    await database.close()


@pytest.mark.asyncio
async def test_task_manager_retries_flood_wait_and_reports_network_error(
    tmp_path: Path,
) -> None:
    url = database_url(tmp_path / "errors.db")
    upgrade_database(url)
    database = Database(url)
    collector = SequenceCollector(
        [
            CollectorError("flood_wait", "wait", wait_seconds=0),
            records(),
            CollectorError("network_unavailable", "Соединение потеряно."),
        ]
    )
    manager = TaskManager(
        database, collector, FakeSessionManager(), FakeGroupService(), batch_size=10
    )
    await manager.initialize()

    recovered = await manager.start(-1001)
    await wait_finished(manager, recovered.id)
    recovered_result = await manager.get(recovered.id)
    assert recovered_result is not None
    assert recovered_result.status is TaskStatus.COMPLETED
    assert recovered_result.saved_count == 2

    failed = await manager.start(-1001)
    await wait_finished(manager, failed.id)
    failed_result = await manager.get(failed.id)
    assert failed_result is not None
    assert failed_result.status is TaskStatus.FAILED
    assert failed_result.error_code == "network_unavailable"
    assert failed_result.error_count == 1
    await database.close()


def test_tasks_api_and_websocket_publish_progress(tmp_path: Path) -> None:
    url = database_url(tmp_path / "api-tasks.db")
    upgrade_database(url)
    database = Database(url)
    manager = TaskManager(
        database,
        SequenceCollector([records()]),
        FakeSessionManager(),
        FakeGroupService(),
        batch_size=1,
    )
    app = create_app(
        session_manager=TelegramSessionManager(tmp_path / "telegram"),
        group_service=FakeGroupService(),  # type: ignore[arg-type]
        database=database,
        task_manager=manager,
    )

    with TestClient(app) as api:
        with api.websocket_connect("/ws/tasks") as websocket:
            started = api.post("/api/tasks/parse", json={"group_id": -1001})
            event = websocket.receive_json()
        assert started.status_code == 202
        assert event["id"] == started.json()["id"]

        task_id = started.json()["id"]
        detail = api.get(f"/api/tasks/{task_id}")
        for _ in range(50):
            if detail.json()["status"] == "completed":
                break
            time.sleep(0.01)
            detail = api.get(f"/api/tasks/{task_id}")
        history = api.get("/api/tasks")

    assert detail.status_code == 200
    assert detail.json()["status"] == "completed"
    assert detail.json()["saved_count"] == 2
    assert history.status_code == 200
    assert history.json()["total"] == 1
