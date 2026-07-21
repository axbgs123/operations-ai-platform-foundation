"""Create versioned platform account configuration.

Revision ID: 20260721_0003
Revises: 20260721_0002
Create Date: 2026-07-21
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260721_0003"
down_revision: str | None = "20260721_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

platform_type = sa.Enum(
    "douyin",
    "xiaohongshu",
    name="content_platform",
    native_enum=False,
)
column_campaign_kind_type = sa.Enum(
    "column",
    "campaign",
    name="column_campaign_kind",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "platform_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", platform_type, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_platform_accounts_workspace_id", "platform_accounts", ["workspace_id"])
    for table_name in ("objective_profiles", "benchmark_profiles"):
        columns = [
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("account_id", sa.Uuid(), sa.ForeignKey("platform_accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
        ]
        if table_name == "objective_profiles":
            columns.extend([sa.Column("objectives", sa.JSON(), nullable=False), sa.Column("metric_weights", sa.JSON(), nullable=False)])
        else:
            columns.append(sa.Column("sample_size", sa.Integer(), nullable=False))
        columns.extend([
            sa.Column("is_account_default", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        ])
        op.create_table(table_name, *columns)
        op.create_index(f"ix_{table_name}_workspace_id", table_name, ["workspace_id"])
        op.create_index(f"ix_{table_name}_account_id", table_name, ["account_id"])
    op.create_unique_constraint("uq_objective_account_version", "objective_profiles", ["account_id", "version"])
    op.create_unique_constraint("uq_benchmark_account_version", "benchmark_profiles", ["account_id", "version"])
    op.create_table(
        "columns_campaigns",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("platform_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", column_campaign_kind_type, nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("objective_profile_id", sa.Uuid(), sa.ForeignKey("objective_profiles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("benchmark_profile_id", sa.Uuid(), sa.ForeignKey("benchmark_profiles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_columns_campaigns_workspace_id", "columns_campaigns", ["workspace_id"])
    op.create_index("ix_columns_campaigns_account_id", "columns_campaigns", ["account_id"])


def downgrade() -> None:
    op.drop_table("columns_campaigns")
    op.drop_table("benchmark_profiles")
    op.drop_table("objective_profiles")
    op.drop_table("platform_accounts")
