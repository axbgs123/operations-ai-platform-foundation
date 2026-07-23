"""Add persistent text generation runs.

Revision ID: 20260723_0016
Revises: 20260723_0015
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_0016"
down_revision: str | None = "20260723_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

status_type = sa.Enum(
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    name="text_generation_run_status",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "text_generation_runs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("platform_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "model_config_id",
            sa.Uuid(),
            sa.ForeignKey("model_configs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("status", status_type, nullable=False),
        sa.Column("original_result", sa.JSON(), nullable=True),
        sa.Column("final_title", sa.Text(), nullable=True),
        sa.Column("final_copy", sa.Text(), nullable=True),
        sa.Column(
            "adoption_status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "modification_magnitude",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "retry_of_run_id",
            sa.Uuid(),
            sa.ForeignKey("text_generation_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "requested_by",
            sa.Uuid(),
            sa.ForeignKey("workspace_members.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("status_detail", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_text_generation_runs_workspace_id",
        "text_generation_runs",
        ["workspace_id"],
    )
    op.create_index(
        "ix_text_generation_runs_cache_key",
        "text_generation_runs",
        ["cache_key"],
    )
    op.create_index(
        "uq_text_generation_runs_active_cache",
        "text_generation_runs",
        ["workspace_id", "cache_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running', 'succeeded')"),
        sqlite_where=sa.text("status IN ('queued', 'running', 'succeeded')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_text_generation_runs_active_cache",
        table_name="text_generation_runs",
    )
    op.drop_index(
        "ix_text_generation_runs_cache_key",
        table_name="text_generation_runs",
    )
    op.drop_index(
        "ix_text_generation_runs_workspace_id",
        table_name="text_generation_runs",
    )
    op.drop_table("text_generation_runs")
