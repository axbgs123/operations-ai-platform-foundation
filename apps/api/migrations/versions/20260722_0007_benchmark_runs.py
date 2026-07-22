"""Persist reproducible dynamic benchmark runs.

Revision ID: 20260722_0007
Revises: 20260722_0006
Create Date: 2026-07-22
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0007"
down_revision: str | None = "20260722_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

platform_type = sa.Enum(
    "douyin", "xiaohongshu", name="content_platform", native_enum=False
)
content_type = sa.Enum(
    "video", "image_text", name="metric_content_type", native_enum=False
)


def upgrade() -> None:
    op.create_table(
        "benchmark_runs",
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
        sa.Column("platform", platform_type, nullable=False),
        sa.Column("content_type", content_type, nullable=False),
        sa.Column("maturity_bucket", sa.String(length=8), nullable=False),
        sa.Column("range_settings", sa.JSON(), nullable=False),
        sa.Column("sample_snapshot_ids", sa.JSON(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("percentile_values", sa.JSON(), nullable=False),
        sa.Column("weights", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.String(length=32), nullable=False),
        sa.Column("algorithm_version", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_benchmark_runs_workspace_id", "benchmark_runs", ["workspace_id"]
    )
    op.create_index(
        "ix_benchmark_runs_account_id", "benchmark_runs", ["account_id"]
    )


def downgrade() -> None:
    op.drop_table("benchmark_runs")
