"""Add public data provider bindings and collection jobs.

Revision ID: 20260904_0045
Revises: 20260813_0044
Create Date: 2026-09-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260904_0045"
down_revision: str | None = "20260813_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

platform_type = sa.Enum(
    "douyin", "xiaohongshu", name="content_platform", native_enum=False
)
provider_status = sa.Enum(
    "unverified", "verified", "disabled",
    name="public_provider_config_status", native_enum=False,
)
binding_status = sa.Enum(
    "active", "error", "disabled",
    name="public_content_binding_status", native_enum=False,
)
job_status = sa.Enum(
    "scheduled", "running", "retrying", "succeeded", "failed", "cancelled",
    name="public_collection_job_status", native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "public_data_provider_configs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("endpoint_region", sa.String(length=20), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("status", provider_status, nullable=False),
        sa.Column("daily_request_limit", sa.Integer(), nullable=False),
        sa.Column("daily_usage_date", sa.Date(), nullable=True),
        sa.Column("daily_requests_used", sa.Integer(), nullable=False),
        sa.Column("configuration_revision", sa.Integer(), nullable=False),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safe_error_code", sa.String(length=100), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "provider", name="uq_public_provider_workspace"),
    )
    op.create_index("ix_public_provider_workspace", "public_data_provider_configs", ["workspace_id"])

    op.create_table(
        "published_content_bindings",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("content_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("platform", platform_type, nullable=False),
        sa.Column("public_url", sa.String(length=2048), nullable=False),
        sa.Column("platform_content_id", sa.String(length=255), nullable=False),
        sa.Column("locator", sa.JSON(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", binding_status, nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safe_error_code", sa.String(length=100), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["content_id"], ["contents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["platform_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_id", name="uq_public_binding_content"),
        sa.UniqueConstraint(
            "workspace_id", "platform", "platform_content_id",
            name="uq_public_binding_platform_content",
        ),
    )
    op.create_index("ix_public_binding_workspace", "published_content_bindings", ["workspace_id"])
    op.create_index("ix_public_binding_account", "published_content_bindings", ["account_id"])

    op.create_table(
        "public_collection_jobs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("target_window", sa.String(length=40), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", job_status, nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("claim_token", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observation_id", sa.Uuid(), nullable=True),
        sa.Column("snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("safe_error_code", sa.String(length=100), nullable=True),
        sa.Column("operation_version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["binding_id"], ["published_content_bindings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("binding_id", "target_window", name="uq_public_collection_binding_window"),
    )
    op.create_index("ix_public_collection_due", "public_collection_jobs", ["status", "next_attempt_at"])
    op.create_index("ix_public_collection_workspace", "public_collection_jobs", ["workspace_id"])

    op.create_table(
        "public_collection_attempts",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("endpoint_contract", sa.String(length=160), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("provider_request_id", sa.String(length=160), nullable=True),
        sa.Column("safe_error_code", sa.String(length=100), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["public_collection_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "attempt_number", name="uq_public_collection_attempt"),
    )
    op.create_index(
        "ix_public_collection_attempt_workspace",
        "public_collection_attempts",
        ["workspace_id", "started_at"],
    )

    op.create_table(
        "public_observations",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("platform", platform_type, nullable=False),
        sa.Column("platform_content_id", sa.String(length=255), nullable=False),
        sa.Column("endpoint_contract", sa.String(length=160), nullable=False),
        sa.Column("parser_version", sa.String(length=80), nullable=False),
        sa.Column("provider_fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_response", sa.JSON(), nullable=False),
        sa.Column("raw_sha256", sa.String(length=64), nullable=False),
        sa.Column("normalized_metrics", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["binding_id"], ["published_content_bindings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_public_observation_workspace", "public_observations", ["workspace_id", "received_at"])
    op.create_index("ix_public_observation_external", "public_observations", ["platform", "platform_content_id"])


def downgrade() -> None:
    op.drop_table("public_observations")
    op.drop_table("public_collection_attempts")
    op.drop_table("public_collection_jobs")
    op.drop_table("published_content_bindings")
    op.drop_table("public_data_provider_configs")
