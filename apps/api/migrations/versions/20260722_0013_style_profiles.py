"""Add explicit versioned account style profiles.

Revision ID: 20260722_0013
Revises: 20260722_0012
Create Date: 2026-07-22
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0013"
down_revision: str | None = "20260722_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

style_profile_status = sa.Enum(
    "pending_confirmation",
    "confirmed",
    name="style_profile_status",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "style_samples",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("platform_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope_key", sa.String(length=80), nullable=False),
        sa.Column("content_id", sa.Uuid(), sa.ForeignKey("contents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("column_campaign_id", sa.Uuid(), sa.ForeignKey("columns_campaigns.id", ondelete="SET NULL"), nullable=True),
        sa.Column("selected_by", sa.Uuid(), sa.ForeignKey("workspace_members.id", ondelete="SET NULL"), nullable=True),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "scope_key", "content_id", name="uq_style_sample_account_scope_content"),
    )
    op.create_index("ix_style_samples_workspace_id", "style_samples", ["workspace_id"])
    op.create_index("ix_style_samples_account_id", "style_samples", ["account_id"])
    op.create_table(
        "account_style_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("platform_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope_key", sa.String(length=80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", style_profile_status, nullable=False),
        sa.Column("style", sa.JSON(), nullable=False),
        sa.Column("sample_content_ids", sa.JSON(), nullable=False),
        sa.Column("diff", sa.JSON(), nullable=False),
        sa.Column("column_campaign_id", sa.Uuid(), sa.ForeignKey("columns_campaigns.id", ondelete="SET NULL"), nullable=True),
        sa.Column("base_profile_id", sa.Uuid(), sa.ForeignKey("account_style_profiles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("workspace_members.id", ondelete="SET NULL"), nullable=True),
        sa.Column("confirmed_by", sa.Uuid(), sa.ForeignKey("workspace_members.id", ondelete="SET NULL"), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "scope_key", "version", name="uq_style_profile_account_scope_version"),
    )
    op.create_index("ix_style_profiles_workspace_id", "account_style_profiles", ["workspace_id"])
    op.create_index("ix_style_profiles_account_id", "account_style_profiles", ["account_id"])
    op.create_index("ix_style_profiles_column_campaign_id", "account_style_profiles", ["column_campaign_id"])


def downgrade() -> None:
    op.drop_index("ix_style_profiles_column_campaign_id", table_name="account_style_profiles")
    op.drop_index("ix_style_profiles_account_id", table_name="account_style_profiles")
    op.drop_index("ix_style_profiles_workspace_id", table_name="account_style_profiles")
    op.drop_table("account_style_profiles")
    op.drop_index("ix_style_samples_account_id", table_name="style_samples")
    op.drop_index("ix_style_samples_workspace_id", table_name="style_samples")
    op.drop_table("style_samples")
