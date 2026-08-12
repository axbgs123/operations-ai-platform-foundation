"""Add private operations agent chat history.

Revision ID: 20260812_0041
Revises: 20260812_0040
Create Date: 2026-08-12
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260812_0041"
down_revision: str | None = "20260812_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

chat_status_type = sa.Enum(
    "active",
    "archived",
    name="agent_chat_status",
    native_enum=False,
)
chat_role_type = sa.Enum(
    "user",
    "assistant",
    "system_event",
    name="agent_chat_role",
    native_enum=False,
)
chat_message_kind_type = sa.Enum(
    "text",
    "plan",
    "run",
    "confirmation",
    "artifact",
    "safe_error",
    name="agent_chat_message_kind",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "agent_chat_sessions",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("owner_member_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("status", chat_status_type, nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_agent_chat_sessions_status"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_member_id"], ["workspace_members.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_agent_chat_sessions_workspace_idempotency"),
    )
    op.create_index(
        "ix_agent_chat_sessions_owner_updated",
        "agent_chat_sessions",
        ["workspace_id", "owner_member_id", "updated_at"],
    )
    op.create_table(
        "agent_chat_messages",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("owner_member_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("role", chat_role_type, nullable=False),
        sa.Column("kind", chat_message_kind_type, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence_no >= 1", name="ck_agent_chat_messages_sequence"),
        sa.CheckConstraint("role IN ('user', 'assistant', 'system_event')", name="ck_agent_chat_messages_role"),
        sa.CheckConstraint("kind IN ('text', 'plan', 'run', 'confirmation', 'artifact', 'safe_error')", name="ck_agent_chat_messages_kind"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["agent_chat_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_member_id"], ["workspace_members.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["agent_plans.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_agent_chat_messages_workspace_idempotency"),
        sa.UniqueConstraint("workspace_id", "session_id", "sequence_no", name="uq_agent_chat_messages_session_sequence"),
    )
    op.create_index(
        "ix_agent_chat_messages_session_sequence",
        "agent_chat_messages",
        ["session_id", "sequence_no"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_chat_messages_session_sequence", table_name="agent_chat_messages")
    op.drop_table("agent_chat_messages")
    op.drop_index("ix_agent_chat_sessions_owner_updated", table_name="agent_chat_sessions")
    op.drop_table("agent_chat_sessions")
