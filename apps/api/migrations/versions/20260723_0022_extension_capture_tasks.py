"""Add extension capture staging tasks.

Revision ID: 20260723_0022
Revises: 20260723_0021
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260723_0022"
down_revision: str | None = "20260723_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "extension_capture_tasks",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("token_id", sa.Uuid(), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column(
            "platform",
            sa.Enum(
                "douyin",
                "xiaohongshu",
                name="content_platform",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("page_version", sa.String(length=80), nullable=False),
        sa.Column("page_identifier", sa.String(length=160), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.String(length=300), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                "retrying",
                "cancelled",
                name="capture_task_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("recognition_output", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("review_url", sa.String(length=300), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("formal_snapshot_ids", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["token_id"], ["extension_tokens.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["member_id"], ["workspace_members.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["confirmed_by"], ["workspace_members.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "token_id", "idempotency_key",
            name="uq_extension_capture_tasks_idempotency",
        ),
    )
    op.create_index(
        "ix_extension_capture_tasks_workspace_id",
        "extension_capture_tasks",
        ["workspace_id"],
    )
    op.create_index(
        "ix_extension_capture_tasks_token_id",
        "extension_capture_tasks",
        ["token_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_extension_capture_tasks_token_id", table_name="extension_capture_tasks")
    op.drop_index("ix_extension_capture_tasks_workspace_id", table_name="extension_capture_tasks")
    op.drop_table("extension_capture_tasks")
