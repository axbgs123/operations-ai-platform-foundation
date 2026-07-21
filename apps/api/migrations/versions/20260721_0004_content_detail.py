"""Create content detail and assets.

Revision ID: 20260721_0004
Revises: 20260721_0003
Create Date: 2026-07-21
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260721_0004"
down_revision: str | None = "20260721_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

platform_type = sa.Enum("douyin", "xiaohongshu", name="content_platform", native_enum=False)
content_status_type = sa.Enum("draft", "published", "archived", name="content_status", native_enum=False)
asset_category_type = sa.Enum("cover", "screenshot", "reference_image", "document", name="asset_category", native_enum=False)


def timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "contents",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("platform_accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("platform", platform_type, nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("objective_profile_id", sa.Uuid(), sa.ForeignKey("objective_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("benchmark_profile_id", sa.Uuid(), sa.ForeignKey("benchmark_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("column_campaign_id", sa.Uuid(), sa.ForeignKey("columns_campaigns.id", ondelete="SET NULL"), nullable=True),
        sa.Column("work_url", sa.String(length=2048), nullable=True),
        sa.Column("status", content_status_type, nullable=False),
        sa.Column("published_title", sa.String(length=300), nullable=True),
        sa.Column("published_body", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
    )
    op.create_index("ix_contents_workspace_id", "contents", ["workspace_id"])
    op.create_index("ix_contents_account_id", "contents", ["account_id"])
    op.create_table(
        "content_assets",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_id", sa.Uuid(), sa.ForeignKey("contents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", asset_category_type, nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_content_assets_workspace_id", "content_assets", ["workspace_id"])
    op.create_index("ix_content_assets_content_id", "content_assets", ["content_id"])
    op.create_index("ix_content_assets_object_key", "content_assets", ["object_key"], unique=True)
    op.create_table(
        "deleted_items",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("deleted_by", sa.Uuid(), sa.ForeignKey("workspace_members.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_deleted_items_workspace_id", "deleted_items", ["workspace_id"])
    op.create_index("ix_deleted_items_resource", "deleted_items", ["resource_type", "resource_id"])


def downgrade() -> None:
    op.drop_table("deleted_items")
    op.drop_table("content_assets")
    op.drop_table("contents")
