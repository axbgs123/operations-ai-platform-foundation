"""Add citation-bearing hotspot research records.

Revision ID: 20260813_0044
Revises: 20260813_0043
Create Date: 2026-08-13
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260813_0044"
down_revision: str | None = "20260813_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

platform_type = sa.Enum(
    "douyin", "xiaohongshu", name="content_platform", native_enum=False
)
research_status_type = sa.Enum(
    "running",
    "succeeded",
    "failed",
    name="hotspot_research_status",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "hotspot_research",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("platform", platform_type, nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", research_status_type, nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("model_config_id", sa.Uuid(), nullable=True),
        sa.Column("configuration_version", sa.String(length=100), nullable=False),
        sa.Column("search_contract_version", sa.String(length=120), nullable=False),
        sa.Column("generation_contract_version", sa.String(length=120), nullable=False),
        sa.Column("source_entries", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("key_points", sa.JSON(), nullable=False),
        sa.Column("creative_candidates", sa.JSON(), nullable=False),
        sa.Column("style_profile_id", sa.Uuid(), nullable=True),
        sa.Column("confirmed_fact_ids", sa.JSON(), nullable=False),
        sa.Column("viral_asset_ids", sa.JSON(), nullable=False),
        sa.Column("safe_error_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("saved_content_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "platform IN ('douyin', 'xiaohongshu')",
            name="ck_hotspot_research_platform",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_hotspot_research_status",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["hotspot_snapshots.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["platform_accounts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["workspace_members.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["model_config_id"], ["model_configs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["style_profile_id"], ["account_style_profiles.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["saved_content_id"], ["contents.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "created_by",
            "idempotency_key",
            name="uq_hotspot_research_idempotency",
        ),
    )
    op.create_index(
        "ix_hotspot_research_workspace_created",
        "hotspot_research",
        ["workspace_id", "created_at"],
    )
    op.create_index("ix_hotspot_research_snapshot", "hotspot_research", ["snapshot_id"])
    op.create_index("ix_hotspot_research_account", "hotspot_research", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_hotspot_research_account", table_name="hotspot_research")
    op.drop_index("ix_hotspot_research_snapshot", table_name="hotspot_research")
    op.drop_index(
        "ix_hotspot_research_workspace_created", table_name="hotspot_research"
    )
    op.drop_table("hotspot_research")
