from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from backend.app.db.models import GroupAccessState, GroupType, ParseTask, TaskStatus
from backend.app.db.repositories import (
    AccountRepository,
    GroupRepository,
    TaskRepository,
    UserRecord,
    UserRepository,
)
from backend.app.db.session import Database
from backend.app.telegram.group_service import GroupInfo
from backend.app.telegram.participant_collector import (
    CollectorError,
    ParticipantRecord,
)
from backend.app.telegram.session_manager import AccountInfo

logger = logging.getLogger("telegram_manager.tasks")


class SessionManagerProtocol(Protocol):
    async def status(self) -> AccountInfo | None: ...


class GroupServiceProtocol(Protocol):
    async def get_group(self, group_id: int) -> GroupInfo: ...


class CollectorProtocol(Protocol):
    def collect(self, group_id: int) -> AsyncIterator[ParticipantRecord]: ...


@dataclass(frozen=True)
class TaskSnapshot:
    id: UUID
    group_id: int
    group_title: str
    status: TaskStatus
    processed_count: int
    saved_count: int
    skipped_count: int
    error_count: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None

    @classmethod
    def from_model(cls, task: ParseTask) -> TaskSnapshot:
        return cls(
            id=task.id,
            group_id=task.source_group.telegram_group_id,
            group_title=task.source_group.title,
            status=task.status,
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


class TaskManagerError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class TaskManager:
    def __init__(
        self,
        database: Database,
        collector: CollectorProtocol,
        session_manager: SessionManagerProtocol,
        group_service: GroupServiceProtocol,
        *,
        batch_size: int = 100,
    ) -> None:
        self._database = database
        self._collector = collector
        self._session_manager = session_manager
        self._group_service = group_service
        self._batch_size = batch_size
        self._lock = asyncio.Lock()
        self._active: asyncio.Task[None] | None = None
        self._active_id: UUID | None = None
        self._subscribers: set[asyncio.Queue[TaskSnapshot]] = set()
        self._shutting_down = False

    async def initialize(self) -> None:
        async with self._database.session() as session:
            await TaskRepository(session).mark_interrupted()

    async def start(self, telegram_group_id: int) -> TaskSnapshot:
        account = await self._session_manager.status()
        if account is None:
            raise TaskManagerError(
                "not_authenticated", "Сначала подключите Telegram-аккаунт.", 401
            )
        group = await self._group_service.get_group(telegram_group_id)
        if group.access_state != "available":
            raise TaskManagerError(
                "group_not_checked",
                "Сначала выберите группу и подтвердите доступ к участникам.",
                409,
            )

        async with self._lock:
            if self._active is not None and not self._active.done():
                active_snapshot = (
                    await self.get(self._active_id)
                    if self._active_id is not None
                    else None
                )
                if active_snapshot is not None and active_snapshot.status in {
                    TaskStatus.COMPLETED,
                    TaskStatus.CANCELLED,
                    TaskStatus.FAILED,
                }:
                    self._active = None
                    self._active_id = None
                else:
                    raise TaskManagerError(
                        "task_already_running",
                        "Уже выполняется другая задача сбора.",
                        409,
                    )
            async with self._database.session() as session:
                task_repository = TaskRepository(session)
                if await task_repository.get_active() is not None:
                    raise TaskManagerError(
                        "task_already_running", "Уже выполняется другая задача сбора.", 409
                    )
                db_account = await AccountRepository(session).upsert(
                    telegram_user_id=account.telegram_user_id,
                    display_name=account.display_name,
                    username=account.username,
                    session_path="data/sessions/account.session",
                )
                db_group = await GroupRepository(session).upsert(
                    account_id=db_account.id,
                    telegram_group_id=group.telegram_group_id,
                    title=group.title,
                    username=group.username,
                    group_type=GroupType(group.group_type),
                    access_state=GroupAccessState.AVAILABLE,
                )
                task = await task_repository.create(db_group.id)
                task_id = task.id

            snapshot = await self.get(task_id)
            if snapshot is None:
                raise RuntimeError("created task disappeared")
            self._active_id = task_id
            self._active = asyncio.create_task(
                self._run(task_id, db_group.id, group.telegram_group_id),
                name=f"parse-task-{task_id}",
            )
        await self._publish(snapshot)
        return snapshot

    async def cancel(self, task_id: UUID) -> TaskSnapshot:
        async with self._lock:
            if self._active_id != task_id or self._active is None or self._active.done():
                task = await self.get(task_id)
                if task is None:
                    raise TaskManagerError("task_not_found", "Задача не найдена.", 404)
                if task.status not in {
                    TaskStatus.PENDING,
                    TaskStatus.RUNNING,
                    TaskStatus.WAITING,
                }:
                    raise TaskManagerError(
                        "task_not_active", "Задача уже завершена.", 409
                    )
                raise TaskManagerError(
                    "task_not_active", "Активный процесс задачи не найден.", 409
                )
            running = self._active
            running.cancel()
        try:
            await running
        except asyncio.CancelledError:
            pass
        snapshot = await self.get(task_id)
        if snapshot is None:
            raise TaskManagerError("task_not_found", "Задача не найдена.", 404)
        if snapshot.status in {
            TaskStatus.PENDING,
            TaskStatus.RUNNING,
            TaskStatus.WAITING,
        }:
            await self._set_status(task_id, TaskStatus.CANCELLED)
            snapshot = await self.get(task_id)
            assert snapshot is not None
        async with self._lock:
            if self._active_id == task_id:
                self._active_id = None
                self._active = None
        return snapshot

    async def get(self, task_id: UUID) -> TaskSnapshot | None:
        async with self._database.session() as session:
            task = await TaskRepository(session).get(task_id)
            return TaskSnapshot.from_model(task) if task is not None else None

    async def list(self, *, page: int, page_size: int) -> tuple[list[TaskSnapshot], int]:
        async with self._database.session() as session:
            tasks, total = await TaskRepository(session).list(
                page=page, page_size=page_size
            )
            return [TaskSnapshot.from_model(task) for task in tasks], total

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[TaskSnapshot]]:
        queue: asyncio.Queue[TaskSnapshot] = asyncio.Queue(maxsize=20)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    async def close(self) -> None:
        self._shutting_down = True
        async with self._lock:
            running = self._active
            if running is not None and not running.done():
                running.cancel()
        if running is not None:
            try:
                await running
            except asyncio.CancelledError:
                pass
        if self._active_id is not None:
            snapshot = await self.get(self._active_id)
            if snapshot is not None and snapshot.status in {
                TaskStatus.PENDING,
                TaskStatus.RUNNING,
                TaskStatus.WAITING,
            }:
                await self._set_status(
                    self._active_id,
                    TaskStatus.FAILED,
                    error_code="interrupted",
                    error_message="Задача прервана завершением приложения.",
                )
            self._active_id = None
            self._active = None

    async def _run(self, task_id: UUID, db_group_id: int, telegram_group_id: int) -> None:
        processed = saved = errors_count = 0
        batch: list[ParticipantRecord] = []
        try:
            await self._set_status(task_id, TaskStatus.RUNNING)
            while True:
                try:
                    async for record in self._collector.collect(telegram_group_id):
                        batch.append(record)
                        processed += 1
                        if len(batch) >= self._batch_size:
                            saved += await self._flush(
                                task_id, db_group_id, batch, processed, saved, errors_count
                            )
                            batch.clear()
                    break
                except CollectorError as exc:
                    if batch:
                        saved += await self._flush(
                            task_id, db_group_id, batch, processed, saved, errors_count
                        )
                        batch.clear()
                    if exc.code != "flood_wait" or exc.wait_seconds is None:
                        raise
                    await self._set_status(
                        task_id,
                        TaskStatus.WAITING,
                        error_code=exc.code,
                        error_message=exc.message,
                    )
                    await asyncio.sleep(exc.wait_seconds)
                    await self._set_status(task_id, TaskStatus.RUNNING)
            if batch:
                saved += await self._flush(
                    task_id, db_group_id, batch, processed, saved, errors_count
                )
                batch.clear()
            await self._set_status(task_id, TaskStatus.COMPLETED)
        except asyncio.CancelledError:
            if batch:
                saved += await asyncio.shield(
                    self._flush(
                        task_id, db_group_id, batch, processed, saved, errors_count
                    )
                )
            if self._shutting_down:
                await asyncio.shield(
                    self._set_status(
                        task_id,
                        TaskStatus.FAILED,
                        error_code="interrupted",
                        error_message="Задача прервана завершением приложения.",
                    )
                )
            else:
                await asyncio.shield(self._set_status(task_id, TaskStatus.CANCELLED))
            raise
        except CollectorError as exc:
            errors_count += 1
            await self._update_progress(task_id, processed, saved, errors_count)
            await self._set_status(
                task_id,
                TaskStatus.FAILED,
                error_code=exc.code,
                error_message=exc.message,
            )
        except Exception:
            logger.exception("Task %s failed", task_id)
            errors_count += 1
            await self._update_progress(task_id, processed, saved, errors_count)
            await self._set_status(
                task_id,
                TaskStatus.FAILED,
                error_code="internal_error",
                error_message="Не удалось сохранить результаты сбора.",
            )
        finally:
            async with self._lock:
                if self._active_id == task_id:
                    self._active_id = None
                    self._active = None

    async def _flush(
        self,
        task_id: UUID,
        group_id: int,
        records: list[ParticipantRecord],
        processed: int,
        saved_before: int,
        errors_count: int,
    ) -> int:
        unique = {record.telegram_user_id: record for record in records}
        async with self._database.session() as session:
            users = UserRepository(session)
            values = [
                UserRecord(
                    record.telegram_user_id,
                    record.username,
                    record.first_name,
                    record.last_name,
                    record.is_bot,
                )
                for record in unique.values()
            ]
            await users.upsert_many(values)
            ids = list(unique)
            await users.link_group_members(group_id, ids)
            added = await users.link_task_members(task_id, ids)
            saved = saved_before + added
            await TaskRepository(session).update_progress(
                task_id,
                processed=processed,
                saved=saved,
                skipped=processed - saved,
                errors_count=errors_count,
            )
        snapshot = await self.get(task_id)
        if snapshot is not None:
            await self._publish(snapshot)
        return added

    async def _update_progress(
        self, task_id: UUID, processed: int, saved: int, errors_count: int
    ) -> None:
        async with self._database.session() as session:
            await TaskRepository(session).update_progress(
                task_id,
                processed=processed,
                saved=saved,
                skipped=processed - saved,
                errors_count=errors_count,
            )

    async def _set_status(
        self,
        task_id: UUID,
        status: TaskStatus,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        async with self._database.session() as session:
            await TaskRepository(session).update_status(
                task_id,
                status,
                error_code=error_code,
                error_message=error_message,
            )
        snapshot = await self.get(task_id)
        if snapshot is not None:
            await self._publish(snapshot)

    async def _publish(self, snapshot: TaskSnapshot) -> None:
        for queue in tuple(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(snapshot)
