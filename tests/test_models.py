from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db.models import (
    Account,
    Base,
    GroupAccessState,
    GroupMember,
    GroupType,
    ParseTask,
    TaskMember,
    TaskStatus,
    TelegramGroup,
    TelegramUser,
)


@pytest.fixture
def engine() -> Iterator[Engine]:
    db_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(db_engine)
    try:
        yield db_engine
    finally:
        db_engine.dispose()


def test_metadata_creates_expected_tables(engine: Engine) -> None:
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == {
        "accounts",
        "groups",
        "group_members",
        "parse_tasks",
        "task_members",
        "users",
    }
    assert {index["name"] for index in inspector.get_indexes("parse_tasks")} == {
        "ix_parse_tasks_status_created_at"
    }
    assert {index["name"] for index in inspector.get_indexes("task_members")} == {
        "ix_task_members_task_id"
    }
    assert {index["name"] for index in inspector.get_indexes("users")} == {
        "ix_users_username"
    }
    assert {
        constraint["name"] for constraint in inspector.get_unique_constraints("groups")
    } == {"uq_groups_account_telegram_group"}


def test_models_store_task_and_memberships(engine: Engine) -> None:
    account = Account(session_path="data/sessions/main.session")
    group = TelegramGroup(
        account=account,
        telegram_group_id=10001,
        title="Test group",
        group_type=GroupType.SUPERGROUP,
    )
    user = TelegramUser(
        telegram_user_id=20002,
        username="test_user",
        first_name="Test",
    )
    task = ParseTask(source_group=group)
    task.members.append(TaskMember(user=user))
    group.members.append(GroupMember(user=user))

    with Session(engine) as session:
        session.add(account)
        session.commit()

        assert isinstance(task.id, UUID)
        assert task.status is TaskStatus.PENDING
        assert task.processed_count == 0
        assert group.access_state is GroupAccessState.UNKNOWN
        assert user.is_bot is False
        assert task.members[0].collected_at is not None
        assert group.members[0].first_seen_at is not None

    with engine.connect() as connection:
        stored_status = connection.exec_driver_sql(
            "SELECT status FROM parse_tasks"
        ).scalar_one()
        assert stored_status == "pending"


def test_group_is_unique_per_account(engine: Engine) -> None:
    account = Account(session_path="data/sessions/main.session")
    account.groups.extend(
        [
            TelegramGroup(
                telegram_group_id=10001,
                title="First",
                group_type=GroupType.GROUP,
            ),
            TelegramGroup(
                telegram_group_id=10001,
                title="Duplicate",
                group_type=GroupType.GROUP,
            ),
        ]
    )

    with Session(engine) as session:
        session.add(account)
        with pytest.raises(IntegrityError):
            session.commit()


def test_task_counters_cannot_be_negative(engine: Engine) -> None:
    account = Account(session_path="data/sessions/main.session")
    group = TelegramGroup(
        account=account,
        telegram_group_id=10001,
        title="Test group",
        group_type=GroupType.GROUP,
    )
    task = ParseTask(source_group=group, processed_count=-1)

    with Session(engine) as session:
        session.add(task)
        with pytest.raises(IntegrityError):
            session.commit()
