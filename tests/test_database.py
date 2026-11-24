from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.exc import IntegrityError

from backend.app.db.migrations import synchronous_database_url, upgrade_database
from backend.app.db.models import (
    GroupAccessState,
    GroupMember,
    GroupType,
    TaskMember,
    TelegramGroup,
    TelegramUser,
)
from backend.app.db.repositories import (
    AccountRepository,
    GroupRepository,
    TaskRepository,
    UserRecord,
    UserRepository,
)
from backend.app.db.session import Database


def database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


def test_initial_migration_applies_to_empty_database(tmp_path: Path) -> None:
    url = database_url(tmp_path / "migration.db")

    upgrade_database(url)
    upgrade_database(url)

    engine = create_engine(synchronous_database_url(url))
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == {
            "accounts",
            "alembic_version",
            "group_members",
            "groups",
            "parse_tasks",
            "task_members",
            "users",
        }
        with engine.connect() as connection:
            revision = connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one()
        assert revision == "20261124_0001"
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_repositories_upsert_and_deduplicate_members(tmp_path: Path) -> None:
    url = database_url(tmp_path / "repositories.db")
    upgrade_database(url)
    database = Database(url)
    users = [
        UserRecord(101, "first", "First", None, False),
        UserRecord(102, "second", "Second", "User", False),
    ]

    async with database.session() as session:
        account_repository = AccountRepository(session)
        group_repository = GroupRepository(session)
        user_repository = UserRepository(session)
        task_repository = TaskRepository(session)

        account = await account_repository.upsert(
            telegram_user_id=1,
            display_name="Owner",
            username="owner",
            session_path="data/sessions/account.session",
        )
        same_account = await account_repository.upsert(
            telegram_user_id=1,
            display_name="Updated Owner",
            username="owner",
            session_path="data/sessions/account.session",
        )
        group = await group_repository.upsert(
            account_id=account.id,
            telegram_group_id=-1001,
            title="Group",
            username="group_name",
            group_type=GroupType.SUPERGROUP,
            access_state=GroupAccessState.AVAILABLE,
        )
        same_group = await group_repository.upsert(
            account_id=account.id,
            telegram_group_id=-1001,
            title="Renamed group",
            username="group_name",
            group_type=GroupType.SUPERGROUP,
            access_state=GroupAccessState.AVAILABLE,
        )
        task = await task_repository.create(group.id)
        await user_repository.upsert_many(users)
        await user_repository.link_group_members(group.id, [101, 102])
        first_saved = await user_repository.link_task_members(task.id, [101, 102])

        await user_repository.upsert_many(
            [UserRecord(101, "renamed", "First", None, False)]
        )
        await user_repository.link_group_members(group.id, [101, 102])
        second_saved = await user_repository.link_task_members(task.id, [101, 102])

        assert account.id == same_account.id
        assert same_account.display_name == "Updated Owner"
        assert group.id == same_group.id
        assert same_group.title == "Renamed group"
        assert first_saved == 2
        assert second_saved == 0

    async with database.session() as session:
        assert await session.scalar(select(func.count()).select_from(TelegramUser)) == 2
        assert await session.scalar(select(func.count()).select_from(TelegramGroup)) == 1
        assert await session.scalar(select(func.count()).select_from(GroupMember)) == 2
        assert await session.scalar(select(func.count()).select_from(TaskMember)) == 2
        assert await session.scalar(
            select(TelegramUser.username).where(TelegramUser.telegram_user_id == 101)
        ) == "renamed"

    await database.close()


@pytest.mark.asyncio
async def test_sqlite_foreign_keys_and_cascade_are_enabled(tmp_path: Path) -> None:
    url = database_url(tmp_path / "foreign_keys.db")
    upgrade_database(url)
    database = Database(url)

    with pytest.raises(IntegrityError):
        async with database.session() as session:
            session.add(GroupMember(group_id=999, telegram_user_id=999))

    async with database.session() as session:
        account = await AccountRepository(session).upsert(
            telegram_user_id=1,
            display_name="Owner",
            username=None,
            session_path="data/sessions/account.session",
        )
        group = await GroupRepository(session).upsert(
            account_id=account.id,
            telegram_group_id=-1001,
            title="Group",
            username=None,
            group_type=GroupType.GROUP,
            access_state=GroupAccessState.AVAILABLE,
        )
        await UserRepository(session).upsert_many(
            [UserRecord(101, None, "First", None, False)]
        )
        await UserRepository(session).link_group_members(group.id, [101])
        await session.delete(group)

    async with database.session() as session:
        assert await session.scalar(select(func.count()).select_from(GroupMember)) == 0

    await database.close()
