"""Govern Qianwen credentials, usage budgets, and validation runs.

Revision ID: 20260729_0033
Revises: 20260728_0032
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260729_0033"
down_revision: str | None = "20260728_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_configs",
        sa.Column(
            "credential_updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "model_configs",
        sa.Column(
            "configuration_revision",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )

    reservation_status = sa.Enum(
        "reserved",
        "settled",
        "released",
        "unknown",
        "expired",
        name="model_usage_reservation_status",
        native_enum=False,
    )
    attempt_status = sa.Enum(
        "succeeded",
        "failed_unbilled",
        "failed_possibly_billed",
        "provider_outcome_unknown",
        "cancelled_unknown",
        name="model_usage_attempt_status",
        native_enum=False,
    )
    validation_result = sa.Enum(
        "passed",
        "failed",
        "not_run",
        name="model_validation_result",
        native_enum=False,
    )

    op.create_table(
        "model_usage_policies",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("max_concurrent_calls", sa.Integer(), nullable=False),
        sa.Column("max_calls_per_minute", sa.Integer(), nullable=False),
        sa.Column("daily_request_limit", sa.Integer(), nullable=False),
        sa.Column("daily_input_token_limit", sa.BigInteger(), nullable=False),
        sa.Column("daily_output_token_limit", sa.BigInteger(), nullable=False),
        sa.Column(
            "daily_embedding_token_limit", sa.BigInteger(), nullable=False
        ),
        sa.Column("daily_ocr_image_limit", sa.Integer(), nullable=False),
        sa.Column(
            "daily_generated_image_limit", sa.Integer(), nullable=False
        ),
        sa.Column(
            "daily_cost_limit_microunits", sa.BigInteger(), nullable=False
        ),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column(
            "effective_from", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "capability",
            "version",
            name="uq_model_usage_policy_workspace_capability_version",
        ),
    )
    op.create_index(
        "ix_model_usage_policy_workspace_capability",
        "model_usage_policies",
        ["workspace_id", "capability", "effective_from"],
    )

    op.create_table(
        "model_usage_reservations",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("model_config_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("provider_attempt_number", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("region", sa.String(length=32), nullable=False),
        sa.Column("capability", sa.String(length=32), nullable=False),
        sa.Column("operation", sa.String(length=48), nullable=False),
        sa.Column("contract_version", sa.String(length=120), nullable=False),
        sa.Column(
            "configuration_version", sa.String(length=100), nullable=False
        ),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("pricing_version", sa.String(length=80), nullable=False),
        sa.Column("estimated_usage", sa.JSON(), nullable=False),
        sa.Column(
            "reserved_cost_microunits", sa.BigInteger(), nullable=False
        ),
        sa.Column("status", reservation_status, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "operation_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["model_config_id"], ["model_configs.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "task_id",
            "attempt_id",
            "provider_attempt_number",
            name="uq_model_usage_reservation_attempt",
        ),
    )
    op.create_index(
        "ix_model_usage_reservation_workspace_created",
        "model_usage_reservations",
        ["workspace_id", "created_at"],
    )
    op.create_index(
        "ix_model_usage_reservation_workspace_capability_status",
        "model_usage_reservations",
        ["workspace_id", "capability", "status"],
    )

    op.create_table(
        "model_usage_attempts",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("provider_attempt_number", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("region", sa.String(length=32), nullable=False),
        sa.Column("capability", sa.String(length=32), nullable=False),
        sa.Column("operation", sa.String(length=48), nullable=False),
        sa.Column("contract_version", sa.String(length=120), nullable=False),
        sa.Column(
            "configuration_version", sa.String(length=100), nullable=False
        ),
        sa.Column("pricing_version", sa.String(length=80), nullable=False),
        sa.Column("usage_basis", sa.String(length=16), nullable=False),
        sa.Column("status", attempt_status, nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("total_tokens", sa.BigInteger(), nullable=False),
        sa.Column("image_inputs", sa.Integer(), nullable=False),
        sa.Column("image_outputs", sa.Integer(), nullable=False),
        sa.Column("embedding_inputs", sa.BigInteger(), nullable=False),
        sa.Column(
            "estimated_cost_microunits", sa.BigInteger(), nullable=False
        ),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("settled_cost_microunits", sa.BigInteger()),
        sa.Column("provider_request_id", sa.String(length=128)),
        sa.Column("stable_error_code", sa.String(length=80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id"],
            ["model_usage_reservations.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "reservation_id",
            name="uq_model_usage_attempt_reservation",
        ),
    )
    op.create_index(
        "ix_model_usage_attempt_workspace_created",
        "model_usage_attempts",
        ["workspace_id", "created_at"],
    )

    op.create_table(
        "model_contract_validation_runs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("model_config_id", sa.Uuid(), nullable=False),
        sa.Column("region", sa.String(length=32), nullable=False),
        sa.Column("capability", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("contract_version", sa.String(length=120), nullable=False),
        sa.Column(
            "configuration_version", sa.String(length=100), nullable=False
        ),
        sa.Column(
            "validation_suite_version", sa.String(length=80), nullable=False
        ),
        sa.Column("max_calls", sa.Integer(), nullable=False),
        sa.Column("max_input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("max_output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("max_images", sa.Integer(), nullable=False),
        sa.Column("max_cost_microunits", sa.BigInteger(), nullable=False),
        sa.Column("result", validation_result, nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("safe_error_code", sa.String(length=80)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["model_config_id"], ["model_configs.id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_model_validation_workspace_created",
        "model_contract_validation_runs",
        ["workspace_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_model_validation_workspace_created",
        table_name="model_contract_validation_runs",
    )
    op.drop_table("model_contract_validation_runs")
    op.drop_index(
        "ix_model_usage_attempt_workspace_created",
        table_name="model_usage_attempts",
    )
    op.drop_table("model_usage_attempts")
    op.drop_index(
        "ix_model_usage_reservation_workspace_capability_status",
        table_name="model_usage_reservations",
    )
    op.drop_index(
        "ix_model_usage_reservation_workspace_created",
        table_name="model_usage_reservations",
    )
    op.drop_table("model_usage_reservations")
    op.drop_index(
        "ix_model_usage_policy_workspace_capability",
        table_name="model_usage_policies",
    )
    op.drop_table("model_usage_policies")
    op.drop_column("model_configs", "configuration_revision")
    op.drop_column("model_configs", "credential_updated_at")
