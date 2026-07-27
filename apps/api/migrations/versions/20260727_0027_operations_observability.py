"""Add append-only task operation events.

Revision ID: 20260727_0027
Revises: 20260727_0026
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260727_0027"
down_revision: str | None = "20260727_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table_name in (
        "text_generation_runs",
        "restore_jobs",
        "workspace_deletion_jobs",
        "extension_capture_tasks",
    ):
        op.add_column(
            table_name,
            sa.Column(
                "operation_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        )
        op.alter_column(
            table_name,
            "operation_version",
            server_default=None,
        )
    op.create_table(
        "task_operation_events",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("task_type", sa.String(length=80), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.Uuid()),
        sa.Column("error_code", sa.String(length=80)),
        sa.Column("failure_stage", sa.String(length=80)),
        sa.Column("result_task_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["workspace_members.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "task_id",
            "action",
            "idempotency_key",
            name="uq_task_operation_events_idempotency",
        ),
    )
    op.create_index(
        "ix_task_operation_events_workspace_task_time",
        "task_operation_events",
        ["workspace_id", "task_type", "created_at"],
    )
    op.create_index(
        "ix_task_operation_events_task",
        "task_operation_events",
        ["task_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_task_operation_events_task",
        table_name="task_operation_events",
    )
    op.drop_index(
        "ix_task_operation_events_workspace_task_time",
        table_name="task_operation_events",
    )
    op.drop_table("task_operation_events")
    for table_name in (
        "extension_capture_tasks",
        "workspace_deletion_jobs",
        "restore_jobs",
        "text_generation_runs",
    ):
        op.drop_column(table_name, "operation_version")
