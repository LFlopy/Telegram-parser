from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.db.models import (
    Account,
    GroupAccessState,
    GroupMember,
    GroupType,
    ParseTask,
    TaskMember,
    TaskStatus,
    TelegramGroup,
    TelegramUser,
)


@dataclass(frozen=True)
class UserRecord:
    telegram_user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    is_bot: bool


class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        telegram_user_id: int,
        display_name: str,
        username: str | None,
        session_path: str,
    ) -> Account:
        account = await self._session.scalar(
            select(Account).where(Account.telegram_user_id == telegram_user_id)
        )
        if account is None:
            account = Account(
                telegram_user_id=telegram_user_id,
                display_name=display_name,
                username=username,
                session_path=session_path,
            )
            self._session.add(account)
        else:
            account.display_name = display_name
            account.username = username
            account.session_path = session_path
        await self._session.flush()
        return account


class GroupRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        account_id: int,
        telegram_group_id: int,
        title: str,
        username: str | None,
        group_type: GroupType,
        access_state: GroupAccessState,
    ) -> TelegramGroup:
        statement = insert(TelegramGroup).values(
            account_id=account_id,
            telegram_group_id=telegram_group_id,
            title=title,
            username=username,
            group_type=group_type,
            access_state=access_state,
            last_checked_at=datetime.now(UTC),
        )
        statement = statement.on_conflict_do_update(
            index_elements=["account_id", "telegram_group_id"],
            set_={
                "title": statement.excluded.title,
                "username": statement.excluded.username,
                "group_type": statement.excluded.group_type,
                "access_state": statement.excluded.access_state,
                "last_checked_at": statement.excluded.last_checked_at,
            },
        )
        await self._session.execute(statement)
        await self._session.flush()
        group = await self._session.scalar(
            select(TelegramGroup).where(
                TelegramGroup.account_id == account_id,
                TelegramGroup.telegram_group_id == telegram_group_id,
            ).execution_options(populate_existing=True)
        )
        if group is None:
            raise RuntimeError("group upsert failed")
        return group

    async def get(self, group_id: int) -> TelegramGroup | None:
        return await self._session.get(TelegramGroup, group_id)


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_many(self, users: Sequence[UserRecord]) -> None:
        if not users:
            return
        values = [
            {
                "telegram_user_id": user.telegram_user_id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "is_bot": user.is_bot,
            }
            for user in users
        ]
        statement = insert(TelegramUser).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=["telegram_user_id"],
            set_={
                "username": statement.excluded.username,
                "first_name": statement.excluded.first_name,
                "last_name": statement.excluded.last_name,
                "is_bot": statement.excluded.is_bot,
                "updated_at": func.current_timestamp(),
            },
        )
        await self._session.execute(statement)

    async def link_group_members(
        self,
        group_id: int,
        telegram_user_ids: Sequence[int],
    ) -> None:
        if not telegram_user_ids:
            return
        statement = insert(GroupMember).values(
            [
                {"group_id": group_id, "telegram_user_id": user_id}
                for user_id in telegram_user_ids
            ]
        )
        statement = statement.on_conflict_do_update(
            index_elements=["group_id", "telegram_user_id"],
            set_={"last_seen_at": func.current_timestamp()},
        )
        await self._session.execute(statement)

    async def link_task_members(
        self,
        task_id: UUID,
        telegram_user_ids: Sequence[int],
    ) -> int:
        unique_ids = set(telegram_user_ids)
        if not unique_ids:
            return 0
        existing = set(
            (
                await self._session.scalars(
                    select(TaskMember.telegram_user_id).where(
                        TaskMember.task_id == task_id,
                        TaskMember.telegram_user_id.in_(unique_ids),
                    )
                )
            ).all()
        )
        new_ids = unique_ids - existing
        if new_ids:
            statement = insert(TaskMember).values(
                [
                    {"task_id": task_id, "telegram_user_id": user_id}
                    for user_id in new_ids
                ]
            )
            statement = statement.on_conflict_do_nothing(
                index_elements=["task_id", "telegram_user_id"]
            )
            await self._session.execute(statement)
        return len(new_ids)


class TaskResultRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_members(
        self,
        task_id: UUID,
        *,
        search: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[UserRecord], int]:
        filters = [TaskMember.task_id == task_id]
        query = (search or "").strip()
        if query:
            escaped = query.replace("%", r"\%").replace("_", r"\_")
            pattern = "%" + escaped + "%"
            filters.append(
                or_(
                    TelegramUser.username.ilike(pattern, escape="\\"),
                    TelegramUser.first_name.ilike(pattern, escape="\\"),
                    TelegramUser.last_name.ilike(pattern, escape="\\"),
                )
            )
        joined = TaskMember.__table__.join(
            TelegramUser,
            TaskMember.telegram_user_id == TelegramUser.telegram_user_id,
        )
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(joined).where(*filters)
            )
            or 0
        )
        users = (
            await self._session.scalars(
                select(TelegramUser)
                .join(TaskMember)
                .where(*filters)
                .order_by(TelegramUser.telegram_user_id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return [
            UserRecord(
                user.telegram_user_id,
                user.username,
                user.first_name,
                user.last_name,
                user.is_bot,
            )
            for user in users
        ], total


class TaskRepository:
    ACTIVE_STATUSES = (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.WAITING)

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, source_group_id: int) -> ParseTask:
        task = ParseTask(source_group_id=source_group_id)
        self._session.add(task)
        await self._session.flush()
        return task

    async def get(self, task_id: UUID) -> ParseTask | None:
        return await self._session.scalar(
            select(ParseTask)
            .options(selectinload(ParseTask.source_group))
            .where(ParseTask.id == task_id)
        )

    async def get_active(self) -> ParseTask | None:
        return await self._session.scalar(
            select(ParseTask)
            .where(ParseTask.status.in_(self.ACTIVE_STATUSES))
            .order_by(ParseTask.created_at.desc())
            .limit(1)
        )

    async def list(self, *, page: int, page_size: int) -> tuple[list[ParseTask], int]:
        base = select(ParseTask).options(selectinload(ParseTask.source_group))
        total = int(await self._session.scalar(select(func.count()).select_from(ParseTask)) or 0)
        tasks = list(
            (
                await self._session.scalars(
                    base.order_by(ParseTask.created_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return tasks, total

    async def update_status(
        self,
        task_id: UUID,
        status: TaskStatus,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        values: dict[str, object] = {
            "status": status,
            "error_code": error_code,
            "error_message": error_message,
        }
        if status is TaskStatus.RUNNING:
            values["started_at"] = func.coalesce(
                ParseTask.started_at, datetime.now(UTC)
            )
        if status in {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED}:
            values["finished_at"] = datetime.now(UTC)
        await self._session.execute(
            update(ParseTask).where(ParseTask.id == task_id).values(**values)
        )

    async def update_progress(
        self,
        task_id: UUID,
        *,
        processed: int,
        saved: int,
        skipped: int,
        errors_count: int,
    ) -> None:
        await self._session.execute(
            update(ParseTask)
            .where(ParseTask.id == task_id)
            .values(
                processed_count=processed,
                saved_count=saved,
                skipped_count=skipped,
                error_count=errors_count,
            )
        )

    async def mark_interrupted(self) -> int:
        active_statuses = self.ACTIVE_STATUSES
        interrupted_count = int(
            await self._session.scalar(
                select(func.count())
                .select_from(ParseTask)
                .where(ParseTask.status.in_(active_statuses))
            )
            or 0
        )
        await self._session.execute(
            update(ParseTask)
            .where(ParseTask.status.in_(active_statuses))
            .values(
                status=TaskStatus.FAILED,
                finished_at=datetime.now(UTC),
                error_code="interrupted",
                error_message="Задача прервана предыдущим завершением приложения.",
            )
        )
        return interrupted_count
