from __future__ import annotations

from datetime import datetime
from enum import Enum as PythonEnum
from typing import TypeVar
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EnumType = TypeVar("EnumType", bound=PythonEnum)


def _enum(enum_class: type[EnumType], name: str) -> Enum:
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


class TaskStatus(str, PythonEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class GroupType(str, PythonEnum):
    GROUP = "group"
    SUPERGROUP = "supergroup"


class GroupAccessState(str, PythonEnum):
    UNKNOWN = "unknown"
    AVAILABLE = "available"
    NO_ACCESS = "no_access"


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(64))
    session_path: Mapped[str] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    groups: Mapped[list[TelegramGroup]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class TelegramGroup(Base):
    __tablename__ = "groups"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "telegram_group_id",
            name="uq_groups_account_telegram_group",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE")
    )
    telegram_group_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(64))
    group_type: Mapped[GroupType] = mapped_column(
        _enum(GroupType, "group_type")
    )
    access_state: Mapped[GroupAccessState] = mapped_column(
        _enum(GroupAccessState, "group_access_state"),
        default=GroupAccessState.UNKNOWN,
        server_default=GroupAccessState.UNKNOWN.value,
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    account: Mapped[Account] = relationship(back_populates="groups")
    tasks: Mapped[list[ParseTask]] = relationship(back_populates="source_group")
    members: Mapped[list[GroupMember]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class TelegramUser(Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_username", "username"),)

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    is_bot: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    task_memberships: Mapped[list[TaskMember]] = relationship(
        back_populates="user", passive_deletes=True
    )
    group_memberships: Mapped[list[GroupMember]] = relationship(
        back_populates="user", passive_deletes=True
    )


class ParseTask(Base):
    __tablename__ = "parse_tasks"
    __table_args__ = (
        CheckConstraint(
            "processed_count >= 0 AND saved_count >= 0 "
            "AND skipped_count >= 0 AND error_count >= 0",
            name="ck_parse_tasks_nonnegative_counts",
        ),
        Index("ix_parse_tasks_status_created_at", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="RESTRICT")
    )
    status: Mapped[TaskStatus] = mapped_column(
        _enum(TaskStatus, "task_status"),
        default=TaskStatus.PENDING,
        server_default=TaskStatus.PENDING.value,
    )
    processed_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    saved_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    skipped_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    error_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(1000))

    source_group: Mapped[TelegramGroup] = relationship(back_populates="tasks")
    members: Mapped[list[TaskMember]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class TaskMember(Base):
    __tablename__ = "task_members"
    __table_args__ = (Index("ix_task_members_task_id", "task_id"),)

    task_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("parse_tasks.id", ondelete="CASCADE"), primary_key=True
    )
    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )

    task: Mapped[ParseTask] = relationship(back_populates="members")
    user: Mapped[TelegramUser] = relationship(back_populates="task_memberships")


class GroupMember(Base):
    __tablename__ = "group_members"

    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )

    group: Mapped[TelegramGroup] = relationship(back_populates="members")
    user: Mapped[TelegramUser] = relationship(back_populates="group_memberships")
