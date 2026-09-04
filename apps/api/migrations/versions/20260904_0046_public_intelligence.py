"""Add competitor monitoring and comment demand analysis.

Revision ID: 20260904_0046
Revises: 20260904_0045
Create Date: 2026-09-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260904_0046"
down_revision: str | None = "20260904_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

platform_type = sa.Enum(
    "douyin", "xiaohongshu", name="content_platform", native_enum=False
)
binding_status = sa.Enum(
    "active",
    "error",
    "disabled",
    name="public_content_binding_status",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "competitor_accounts",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("platform", platform_type, nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("public_url", sa.String(length=2048), nullable=False),
        sa.Column("platform_account_id", sa.String(length=255), nullable=False),
        sa.Column("next_collection_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", binding_status, nullable=False),
        sa.Column("collection_interval_hours", sa.Integer(), nullable=False),
        sa.Column("last_collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safe_error_code", sa.String(length=100), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "platform",
            "platform_account_id",
            name="uq_competitor_workspace_platform_account",
        ),
    )
    op.create_index(
        "ix_competitor_workspace", "competitor_accounts", ["workspace_id", "platform"]
    )
    op.create_index(
        "ix_competitor_due", "competitor_accounts", ["status", "next_collection_at"]
    )

    op.create_table(
        "competitor_observations",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("competitor_account_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("platform", platform_type, nullable=False),
        sa.Column("endpoint_contract", sa.String(length=160), nullable=False),
        sa.Column("provider_fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_response", sa.JSON(), nullable=False),
        sa.Column("raw_sha256", sa.String(length=64), nullable=False),
        sa.Column("follower_count", sa.Integer(), nullable=True),
        sa.Column("posts", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["competitor_account_id"], ["competitor_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_competitor_observation_account",
        "competitor_observations",
        ["competitor_account_id", "provider_fetched_at"],
    )
    op.create_index(
        "ix_competitor_observation_workspace",
        "competitor_observations",
        ["workspace_id", "received_at"],
    )

    op.create_table(
        "comment_demand_analyses",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("platform", platform_type, nullable=False),
        sa.Column("public_url", sa.String(length=2048), nullable=False),
        sa.Column("platform_content_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("endpoint_contract", sa.String(length=160), nullable=False),
        sa.Column("provider_fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_response", sa.JSON(), nullable=False),
        sa.Column("raw_sha256", sa.String(length=64), nullable=False),
        sa.Column("comment_count", sa.Integer(), nullable=False),
        sa.Column("themes", sa.JSON(), nullable=False),
        sa.Column("top_questions", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_comment_demand_workspace",
        "comment_demand_analyses",
        ["workspace_id", "received_at"],
    )
    op.create_index(
        "ix_comment_demand_content",
        "comment_demand_analyses",
        ["workspace_id", "platform", "platform_content_id"],
    )

    op.create_table(
        "public_trend_searches",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("platform", platform_type, nullable=False),
        sa.Column("keyword", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("endpoint_contract", sa.String(length=160), nullable=False),
        sa.Column("provider_fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_response", sa.JSON(), nullable=False),
        sa.Column("raw_sha256", sa.String(length=64), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_public_trend_search_workspace",
        "public_trend_searches",
        ["workspace_id", "received_at"],
    )
    op.create_index(
        "ix_public_trend_search_lookup",
        "public_trend_searches",
        ["workspace_id", "platform", "keyword", "received_at"],
    )


def downgrade() -> None:
    op.drop_table("public_trend_searches")
    op.drop_table("comment_demand_analyses")
    op.drop_table("competitor_observations")
    op.drop_table("competitor_accounts")
