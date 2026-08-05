"""Add governed operations-agent runtime records.

Revision ID: 20260805_0034
Revises: 20260729_0033
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260805_0034"
down_revision: str | None = "20260729_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
    )


def upgrade() -> None:
    platform = sa.Enum(
        "douyin",
        "xiaohongshu",
        name="content_platform",
        native_enum=False,
    )
    plan_status = sa.Enum(
        "draft",
        "approved",
        "rejected",
        "invalidated",
        name="agent_plan_status",
        native_enum=False,
    )
    run_status = sa.Enum(
        "draft",
        "awaiting_plan_approval",
        "queued",
        "running",
        "awaiting_action_confirmation",
        "succeeded",
        "rejected",
        "cancelled",
        "failed",
        "configuration_required",
        "compensation_required",
        "provider_outcome_unknown",
        name="agent_run_status",
        native_enum=False,
    )
    step_status = sa.Enum(
        "pending",
        "running",
        "awaiting_action_confirmation",
        "succeeded",
        "rejected",
        "cancelled",
        "failed",
        "compensation_required",
        "provider_outcome_unknown",
        name="agent_step_status",
        native_enum=False,
    )
    confirmation_status = sa.Enum(
        "pending",
        "approved",
        "rejected",
        "expired",
        "invalidated",
        name="agent_confirmation_status",
        native_enum=False,
    )
    tool_risk = sa.Enum(
        "read_only",
        "draft_write",
        "protected_write",
        name="agent_tool_risk",
        native_enum=False,
    )
    artifact_kind = sa.Enum(
        "analysis",
        "draft",
        "cover_recommendation",
        "risk_scan",
        "export",
        name="agent_artifact_kind",
        native_enum=False,
    )

    op.create_table(
        "agent_briefings",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("algorithm_version", sa.String(length=80), nullable=False),
        sa.Column("tool_catalog_version", sa.String(length=80), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("priority_candidate", sa.JSON(), nullable=True),
        sa.Column(
            "data_cutoff_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        *_timestamps(),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "input_fingerprint",
            "algorithm_version",
            name="uq_agent_briefings_workspace_input_algorithm",
        ),
    )
    op.create_index(
        "ix_agent_briefings_workspace_created",
        "agent_briefings",
        ["workspace_id", "created_at"],
    )

    op.create_table(
        "agent_plans",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("briefing_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("platform", platform, nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("tool_catalog_version", sa.String(length=80), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("plan_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", plan_status, nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        *_timestamps(),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.CheckConstraint(
            "platform IN ('douyin', 'xiaohongshu')",
            name="ck_agent_plans_platform",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["briefing_id"],
            ["agent_briefings.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["platform_accounts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["workspace_members.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["workspace_members.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_agent_plans_workspace_idempotency",
        ),
    )
    op.create_index(
        "ix_agent_plans_workspace_created",
        "agent_plans",
        ["workspace_id", "created_at"],
    )
    op.create_index(
        "ix_agent_plans_account",
        "agent_plans",
        ["account_id", "created_at"],
    )

    op.create_table(
        "agent_runs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("platform", platform, nullable=False),
        sa.Column("status", run_status, nullable=False),
        sa.Column("current_step_index", sa.Integer(), nullable=False),
        sa.Column("operation_version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("claim_token", sa.String(length=120), nullable=True),
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("safe_error_code", sa.String(length=80), nullable=True),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        *_timestamps(),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.CheckConstraint(
            "platform IN ('douyin', 'xiaohongshu')",
            name="ck_agent_runs_platform",
        ),
        sa.CheckConstraint(
            "operation_version >= 1",
            name="ck_agent_runs_operation_version",
        ),
        sa.CheckConstraint(
            "current_step_index >= 0",
            name="ck_agent_runs_current_step_index",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["agent_plans.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["platform_accounts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["workspace_members.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "plan_id",
            name="uq_agent_runs_workspace_plan",
        ),
    )
    op.create_index(
        "ix_agent_runs_workspace_status",
        "agent_runs",
        ["workspace_id", "status"],
    )
    op.create_index(
        "ix_agent_runs_account_created",
        "agent_runs",
        ["account_id", "created_at"],
    )

    op.create_table(
        "agent_run_steps",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(length=80), nullable=False),
        sa.Column("tool_version", sa.String(length=40), nullable=False),
        sa.Column("tool_risk", tool_risk, nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("input_envelope", sa.JSON(), nullable=False),
        sa.Column("status", step_status, nullable=False),
        sa.Column("operation_version", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("result_envelope", sa.JSON(), nullable=True),
        sa.Column("safe_error_code", sa.String(length=80), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        *_timestamps(),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.CheckConstraint(
            "step_index >= 0",
            name="ck_agent_steps_step_index",
        ),
        sa.CheckConstraint(
            "operation_version >= 1",
            name="ck_agent_steps_operation_version",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "run_id",
            "step_index",
            name="uq_agent_steps_run_index",
        ),
    )
    op.create_index(
        "ix_agent_steps_workspace_run",
        "agent_run_steps",
        ["workspace_id", "run_id"],
    )
    op.create_index(
        "ix_agent_steps_run_status",
        "agent_run_steps",
        ["run_id", "status"],
    )

    op.create_table(
        "agent_confirmations",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Uuid(), nullable=False),
        sa.Column("action_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("action_summary", sa.JSON(), nullable=False),
        sa.Column("status", confirmation_status, nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        *_timestamps(),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_id"],
            ["agent_run_steps.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["workspace_members.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"],
            ["workspace_members.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "run_id",
            "step_id",
            "action_fingerprint",
            name="uq_agent_confirmations_run_step_action",
        ),
    )
    op.create_index(
        "ix_agent_confirmations_workspace_status",
        "agent_confirmations",
        ["workspace_id", "status"],
    )

    op.create_table(
        "agent_artifacts",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("kind", artifact_kind, nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Uuid(), nullable=True),
        sa.Column("safe_metadata", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_id"],
            ["agent_run_steps.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_agent_artifacts_workspace_run",
        "agent_artifacts",
        ["workspace_id", "run_id"],
    )
    op.create_index(
        "ix_agent_artifacts_resource",
        "agent_artifacts",
        ["resource_type", "resource_id"],
    )

    op.create_table(
        "agent_events",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("safe_payload", sa.JSON(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("step_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_id"],
            ["agent_run_steps.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["workspace_members.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_agent_events_workspace_idempotency",
        ),
    )
    op.create_index(
        "ix_agent_events_workspace_created",
        "agent_events",
        ["workspace_id", "created_at"],
    )
    op.create_index(
        "ix_agent_events_run_created",
        "agent_events",
        ["run_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_events_run_created", table_name="agent_events")
    op.drop_index(
        "ix_agent_events_workspace_created",
        table_name="agent_events",
    )
    op.drop_table("agent_events")
    op.drop_index(
        "ix_agent_artifacts_resource",
        table_name="agent_artifacts",
    )
    op.drop_index(
        "ix_agent_artifacts_workspace_run",
        table_name="agent_artifacts",
    )
    op.drop_table("agent_artifacts")
    op.drop_index(
        "ix_agent_confirmations_workspace_status",
        table_name="agent_confirmations",
    )
    op.drop_table("agent_confirmations")
    op.drop_index(
        "ix_agent_steps_run_status",
        table_name="agent_run_steps",
    )
    op.drop_index(
        "ix_agent_steps_workspace_run",
        table_name="agent_run_steps",
    )
    op.drop_table("agent_run_steps")
    op.drop_index(
        "ix_agent_runs_account_created",
        table_name="agent_runs",
    )
    op.drop_index(
        "ix_agent_runs_workspace_status",
        table_name="agent_runs",
    )
    op.drop_table("agent_runs")
    op.drop_index("ix_agent_plans_account", table_name="agent_plans")
    op.drop_index(
        "ix_agent_plans_workspace_created",
        table_name="agent_plans",
    )
    op.drop_table("agent_plans")
    op.drop_index(
        "ix_agent_briefings_workspace_created",
        table_name="agent_briefings",
    )
    op.drop_table("agent_briefings")
