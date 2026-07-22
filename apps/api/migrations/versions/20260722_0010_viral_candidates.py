"""Add versioned viral thresholds and immutable candidate evidence.

Revision ID: 20260722_0010
Revises: 20260722_0009
Create Date: 2026-07-22
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0010"
down_revision: str | None = "20260722_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

platform_type = sa.Enum(
    "douyin", "xiaohongshu", name="content_platform", native_enum=False
)
content_type = sa.Enum(
    "video", "image_text", name="metric_content_type", native_enum=False
)
viral_category = sa.Enum(
    "traffic", "engagement", "growth", "conversion",
    name="viral_category", native_enum=False,
)
viral_status = sa.Enum(
    "recommended", "confirmed", "revoked",
    name="viral_candidate_status", native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "viral_threshold_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("platform_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column(
            "objective_profile_id",
            sa.Uuid(),
            sa.ForeignKey("objective_profiles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "benchmark_profile_id",
            sa.Uuid(),
            sa.ForeignKey("benchmark_profiles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("workspace_members.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "version", name="uq_viral_threshold_account_version"),
    )
    op.create_index("ix_viral_threshold_profiles_workspace_id", "viral_threshold_profiles", ["workspace_id"])
    op.create_index("ix_viral_threshold_profiles_account_id", "viral_threshold_profiles", ["account_id"])
    op.create_table(
        "viral_candidates",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("platform_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_id", sa.Uuid(), sa.ForeignKey("contents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), sa.ForeignKey("data_snapshots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("platform", platform_type, nullable=False),
        sa.Column("content_type", content_type, nullable=False),
        sa.Column("maturity_bucket", sa.String(length=8), nullable=False),
        sa.Column("category", viral_category, nullable=False),
        sa.Column("metric_key", sa.String(length=80), nullable=False),
        sa.Column("actual_value", sa.Numeric(24, 6), nullable=False),
        sa.Column("percentile", sa.Float(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("threshold_value", sa.Numeric(24, 6), nullable=False),
        sa.Column("threshold_profile_id", sa.Uuid(), sa.ForeignKey("viral_threshold_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("threshold_profile_version", sa.Integer(), nullable=False),
        sa.Column("objective_profile_id", sa.Uuid(), sa.ForeignKey("objective_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("benchmark_profile_id", sa.Uuid(), sa.ForeignKey("benchmark_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("status", viral_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("threshold_profile_id", "content_id", "category", "metric_key", name="uq_viral_candidate_evidence"),
    )
    op.create_index("ix_viral_candidates_workspace_id", "viral_candidates", ["workspace_id"])
    op.create_index("ix_viral_candidates_account_id", "viral_candidates", ["account_id"])
    op.create_index("ix_viral_candidates_content_id", "viral_candidates", ["content_id"])
    op.create_table(
        "viral_library_items",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("platform_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), sa.ForeignKey("viral_candidates.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("content_id", sa.Uuid(), sa.ForeignKey("contents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("category", viral_category, nullable=False),
        sa.Column("strategy_tags", sa.JSON(), nullable=False),
        sa.Column("applicable_scenarios", sa.JSON(), nullable=False),
        sa.Column("structure_summary", sa.Text(), nullable=False),
        sa.Column("confirmed_by", sa.Uuid(), sa.ForeignKey("workspace_members.id", ondelete="SET NULL"), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_by", sa.Uuid(), sa.ForeignKey("workspace_members.id", ondelete="SET NULL"), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("candidate_id", name="uq_viral_library_candidate"),
    )
    op.create_index("ix_viral_library_items_workspace_id", "viral_library_items", ["workspace_id"])
    op.create_index("ix_viral_library_items_account_id", "viral_library_items", ["account_id"])
    op.create_index("ix_viral_library_items_content_id", "viral_library_items", ["content_id"])


def downgrade() -> None:
    op.drop_table("viral_library_items")
    op.drop_table("viral_candidates")
    op.drop_table("viral_threshold_profiles")
