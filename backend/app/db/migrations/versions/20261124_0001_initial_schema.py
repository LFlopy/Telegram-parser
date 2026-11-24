"""Initial database schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261124_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("session_path", sa.String(1024), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp()
        ),
        sa.UniqueConstraint("telegram_user_id", name="uq_accounts_telegram_user_id"),
    )
    op.create_table(
        "users",
        sa.Column("telegram_user_id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("first_name", sa.String(255), nullable=True),
        sa.Column("last_name", sa.String(255), nullable=True),
        sa.Column("is_bot", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp()
        ),
    )
    op.create_index("ix_users_username", "users", ["username"])
    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("telegram_group_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column(
            "group_type",
            sa.Enum(
                "group",
                "supergroup",
                name="group_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "access_state",
            sa.Enum(
                "unknown",
                "available",
                "no_access",
                name="group_access_state",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "account_id",
            "telegram_group_id",
            name="uq_groups_account_telegram_group",
        ),
    )
    op.create_table(
        "parse_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_group_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "waiting",
                "completed",
                "cancelled",
                "failed",
                name="task_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("processed_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("saved_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("skipped_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp()
        ),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(1000), nullable=True),
        sa.CheckConstraint(
            "processed_count >= 0 AND saved_count >= 0 AND skipped_count >= 0 "
            "AND error_count >= 0",
            name="ck_parse_tasks_nonnegative_counts",
        ),
        sa.ForeignKeyConstraint(["source_group_id"], ["groups.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_parse_tasks_status_created_at",
        "parse_tasks",
        ["status", "created_at"],
    )
    op.create_table(
        "group_members",
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp()
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp()
        ),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["telegram_user_id"], ["users.telegram_user_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("group_id", "telegram_user_id"),
    )
    op.create_table(
        "task_members",
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "collected_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp()
        ),
        sa.ForeignKeyConstraint(["task_id"], ["parse_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["telegram_user_id"], ["users.telegram_user_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("task_id", "telegram_user_id"),
    )
    op.create_index("ix_task_members_task_id", "task_members", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_task_members_task_id", table_name="task_members")
    op.drop_table("task_members")
    op.drop_table("group_members")
    op.drop_index("ix_parse_tasks_status_created_at", table_name="parse_tasks")
    op.drop_table("parse_tasks")
    op.drop_table("groups")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
    op.drop_table("accounts")
