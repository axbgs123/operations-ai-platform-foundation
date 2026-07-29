"""Persist governed Qianwen cover generation attempts.

Revision ID: 20260728_0032
Revises: 20260728_0031
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260728_0032"
down_revision: str | None = "20260728_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_status = sa.Enum(
        "queued",
        "running",
        "provider_calling",
        "provider_outcome_unknown",
        "downloading",
        "validating",
        "compositing",
        "risk_scanning",
        "succeeded",
        "failed",
        "cancelled",
        "compensation_required",
        name="cover_generation_status",
        native_enum=False,
    )
    attempt_status = sa.Enum(
        "running",
        "provider_calling",
        "provider_outcome_unknown",
        "downloading",
        "validating",
        "compositing",
        "risk_scanning",
        "succeeded",
        "failed",
        "cancelled",
        "compensation_required",
        name="cover_attempt_status",
        native_enum=False,
    )
    op.create_table(
        "cover_generation_runs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("content_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("contract_version", sa.String(length=100), nullable=False),
        sa.Column("configuration_version", sa.String(length=100), nullable=False),
        sa.Column("cover_mode", sa.String(length=32), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("status", run_status, nullable=False),
        sa.Column(
            "retry_idempotency_keys",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column("model_config_id", sa.Uuid()),
        sa.Column("region", sa.String(length=32)),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("claim_token", sa.String(length=64)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(length=80)),
        sa.Column("status_detail", sa.String(length=240)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "operation_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["workspace_members.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["platform_accounts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["content_id"], ["contents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["model_config_id"], ["model_configs.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "requested_by",
            "idempotency_key",
            name="uq_cover_runs_workspace_member_idempotency",
        ),
    )
    op.create_index(
        "ix_cover_generation_runs_workspace_status",
        "cover_generation_runs",
        ["workspace_id", "status"],
    )
    op.create_index(
        "ix_cover_generation_runs_content_id",
        "cover_generation_runs",
        ["content_id"],
    )

    op.create_table(
        "cover_artifact_attempts",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", attempt_status, nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("configuration_version", sa.String(length=100), nullable=False),
        sa.Column("contract_version", sa.String(length=100), nullable=False),
        sa.Column("cover_mode", sa.String(length=32), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("requested_width", sa.Integer(), nullable=False),
        sa.Column("requested_height", sa.Integer(), nullable=False),
        sa.Column("seed", sa.Integer()),
        sa.Column("previous_attempt_id", sa.Uuid()),
        sa.Column("region", sa.String(length=32)),
        sa.Column("model_config_id", sa.Uuid()),
        sa.Column(
            "input_assets",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column("provider_request_id", sa.String(length=128)),
        sa.Column("provider_started_at", sa.DateTime(timezone=True)),
        sa.Column("provider_completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "billed_attempt_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_started",
        ),
        sa.Column("output_object_key", sa.String(length=1024)),
        sa.Column("output_object_version", sa.String(length=80)),
        sa.Column("output_sha256", sa.String(length=64)),
        sa.Column("output_mime_type", sa.String(length=120)),
        sa.Column("output_width", sa.Integer()),
        sa.Column("output_height", sa.Integer()),
        sa.Column("layout_version", sa.String(length=80)),
        sa.Column("ocr_model_version", sa.String(length=160)),
        sa.Column("ocr_confidence", sa.Float()),
        sa.Column("risk_scan_id", sa.Uuid()),
        sa.Column("risk_rule_version", sa.String(length=160)),
        sa.Column(
            "requires_human_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "publish_eligible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "disclaimer",
            sa.String(length=160),
            nullable=False,
            server_default="辅助判断，不保证通过平台审核",
        ),
        sa.Column("error_code", sa.String(length=80)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "operation_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["cover_generation_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["previous_attempt_id"],
            ["cover_artifact_attempts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_config_id"], ["model_configs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["risk_scan_id"], ["risk_scans.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "run_id",
            "attempt_number",
            name="uq_cover_artifact_attempt_run_number",
        ),
    )
    op.create_index(
        "ix_cover_artifact_attempts_workspace_run",
        "cover_artifact_attempts",
        ["workspace_id", "run_id"],
    )
    op.create_index(
        "ix_cover_artifact_attempts_output_object",
        "cover_artifact_attempts",
        ["output_object_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cover_artifact_attempts_output_object",
        table_name="cover_artifact_attempts",
    )
    op.drop_index(
        "ix_cover_artifact_attempts_workspace_run",
        table_name="cover_artifact_attempts",
    )
    op.drop_table("cover_artifact_attempts")
    op.drop_index(
        "ix_cover_generation_runs_content_id",
        table_name="cover_generation_runs",
    )
    op.drop_index(
        "ix_cover_generation_runs_workspace_status",
        table_name="cover_generation_runs",
    )
    op.drop_table("cover_generation_runs")
