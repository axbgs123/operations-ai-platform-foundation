"""Add evidence-grounded analysis runs, settings, suggestions, and events.

Revision ID: 20260722_0011
Revises: 20260722_0010
Create Date: 2026-07-22
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0011"
down_revision: str | None = "20260722_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

analysis_status = sa.Enum(
    "pending",
    "running",
    "succeeded",
    "failed",
    name="analysis_run_status",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("platform_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_id", sa.Uuid(), sa.ForeignKey("contents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("benchmark_run_id", sa.Uuid(), sa.ForeignKey("benchmark_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("snapshot_ids", sa.JSON(), nullable=False),
        sa.Column("status", analysis_status, nullable=False),
        sa.Column("trigger_kind", sa.String(length=20), nullable=False),
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("evidence_bundle", sa.JSON(), nullable=False),
        sa.Column("model_version", sa.String(length=80), nullable=False),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("algorithm_version", sa.String(length=80), nullable=False),
        sa.Column("benchmark_algorithm_version", sa.String(length=80), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("report", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.Uuid(), sa.ForeignKey("workspace_members.id", ondelete="SET NULL"), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_analysis_runs_workspace_id", "analysis_runs", ["workspace_id"])
    op.create_index("ix_analysis_runs_content_id", "analysis_runs", ["content_id"])
    op.create_index("ix_analysis_runs_cache_key", "analysis_runs", ["cache_key"])
    op.create_index(
        "uq_analysis_runs_active_cache",
        "analysis_runs",
        ["content_id", "cache_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running', 'succeeded')"),
        sqlite_where=sa.text("status IN ('pending', 'running', 'succeeded')"),
    )

    op.create_table(
        "account_analysis_settings",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("platform_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("auto_analyze", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", name="uq_account_analysis_setting_account"),
    )
    op.create_index("ix_account_analysis_settings_workspace_id", "account_analysis_settings", ["workspace_id"])
    op.create_index("ix_account_analysis_settings_account_id", "account_analysis_settings", ["account_id"])

    op.create_table(
        "analysis_suggestions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("analysis_run_id", sa.Uuid(), sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recommendation_id", sa.String(length=80), nullable=False),
        sa.Column("recommendation", sa.JSON(), nullable=False),
        sa.Column("adoption_status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("analysis_run_id", "recommendation_id", name="uq_analysis_suggestion_recommendation"),
    )
    op.create_index("ix_analysis_suggestions_workspace_id", "analysis_suggestions", ["workspace_id"])
    op.create_index("ix_analysis_suggestions_run_id", "analysis_suggestions", ["analysis_run_id"])

    op.create_table(
        "product_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_name", sa.String(length=120), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("workspace_members.id", ondelete="SET NULL"), nullable=True),
        sa.Column("properties", sa.JSON(), nullable=False),
    )
    op.create_index("ix_product_events_workspace_id", "product_events", ["workspace_id"])
    op.create_index("ix_product_events_entity", "product_events", ["entity_type", "entity_id"])


def downgrade() -> None:
    op.drop_table("product_events")
    op.drop_table("analysis_suggestions")
    op.drop_table("account_analysis_settings")
    op.drop_table("analysis_runs")
