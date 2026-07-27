"""Add governed deletion and retention state.

Revision ID: 20260727_0025
Revises: 20260726_0024
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260727_0025"
down_revision: str | None = "20260726_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "status",
            sa.String(length=40),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "workspaces",
        sa.Column(
            "deletion_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.alter_column("workspaces", "status", server_default=None)
    op.alter_column("workspaces", "deletion_version", server_default=None)

    op.add_column(
        "deleted_items",
        sa.Column("scheduled_purge_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        "UPDATE deleted_items "
        "SET scheduled_purge_at = deleted_at + INTERVAL '30 days'"
    )
    op.alter_column(
        "deleted_items",
        "scheduled_purge_at",
        nullable=False,
    )
    op.add_column(
        "deleted_items",
        sa.Column("deletion_reason", sa.String(length=240)),
    )
    op.add_column(
        "deleted_items",
        sa.Column(
            "status",
            sa.Enum(
                "recoverable",
                "restored",
                "purging",
                "purged",
                name="deleted_item_status",
                native_enum=False,
            ),
            nullable=False,
            server_default="recoverable",
        ),
    )
    op.alter_column("deleted_items", "status", server_default=None)

    retention_strategy = sa.Enum(
        "immediate",
        "scheduled",
        "evidence",
        name="retention_strategy",
        native_enum=False,
    )
    managed_state = sa.Enum(
        "active",
        "scheduled",
        "evidence",
        "referenced",
        "retrying",
        "deleted",
        name="managed_object_state",
        native_enum=False,
    )
    deletion_status = sa.Enum(
        "queued",
        "running",
        "succeeded",
        "failed",
        "retrying",
        "cancelled",
        name="workspace_deletion_status",
        native_enum=False,
    )
    deletion_phase = sa.Enum(
        "pending",
        "inventory_created",
        "access_revoked",
        "jobs_cancelled",
        "vectors_deleted",
        "objects_deleting",
        "objects_deleted",
        "caches_deleting",
        "caches_deleted",
        "structured_data_deleting",
        "structured_data_deleted",
        "completed",
        "failed",
        name="workspace_deletion_phase",
        native_enum=False,
    )

    op.create_table(
        "retention_policies",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("strategy", retention_strategy, nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retention_seconds", sa.Integer()),
        sa.Column("created_by", sa.Uuid()),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["workspace_members.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "version",
            name="uq_retention_policies_workspace_version",
        ),
    )
    op.create_index(
        "ix_retention_policies_workspace_effective",
        "retention_policies",
        ["workspace_id", "effective_at"],
    )

    op.create_table(
        "managed_objects",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("owner_type", sa.String(length=80), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("managed_prefix", sa.String(length=1024), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("strategy", retention_strategy, nullable=False),
        sa.Column("state", managed_state, nullable=False),
        sa.Column("object_key", sa.String(length=1024)),
        sa.Column("purge_at", sa.DateTime(timezone=True)),
        sa.Column("evidence_reason", sa.String(length=240)),
        sa.Column("related_resource_type", sa.String(length=80)),
        sa.Column("related_resource_id", sa.Uuid()),
        sa.Column("claim_token", sa.String(length=64)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=80)),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_managed_objects_workspace_state_purge",
        "managed_objects",
        ["workspace_id", "state", "purge_at"],
    )
    op.create_index(
        "ix_managed_objects_owner",
        "managed_objects",
        ["workspace_id", "owner_type", "owner_id"],
    )
    op.create_index(
        "ix_managed_objects_object_key",
        "managed_objects",
        ["object_key"],
        unique=True,
    )

    op.create_table(
        "workspace_deletion_confirmations",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("workspace_version", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        *_timestamps(),
    )
    op.create_index(
        "ix_workspace_deletion_confirmations_workspace",
        "workspace_deletion_confirmations",
        ["workspace_id", "expires_at"],
    )
    op.create_index(
        "ix_workspace_deletion_confirmations_token_hash",
        "workspace_deletion_confirmations",
        ["token_hash"],
        unique=True,
    )

    op.create_table(
        "workspace_deletion_jobs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("inventory", sa.JSON(), nullable=False),
        sa.Column("status", deletion_status, nullable=False),
        sa.Column("phase", deletion_phase, nullable=False),
        sa.Column("claim_token", sa.String(length=64)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(length=80)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "workspace_id",
            "requested_by",
            "idempotency_key",
            name="uq_workspace_deletion_jobs_idempotency",
        ),
    )
    op.create_index(
        "ix_workspace_deletion_jobs_workspace_status",
        "workspace_deletion_jobs",
        ["workspace_id", "status"],
    )

    op.create_table(
        "deletion_audits",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("phase", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Uuid()),
        sa.Column("deletion_job_id", sa.Uuid()),
        sa.Column("resource_id", sa.Uuid()),
        sa.Column("error_code", sa.String(length=80)),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
    )
    op.create_index(
        "ix_deletion_audits_workspace_time",
        "deletion_audits",
        ["workspace_id", "created_at"],
    )
    op.create_index(
        "ix_deletion_audits_job",
        "deletion_audits",
        ["deletion_job_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_deletion_audits_job", table_name="deletion_audits")
    op.drop_index(
        "ix_deletion_audits_workspace_time",
        table_name="deletion_audits",
    )
    op.drop_table("deletion_audits")
    op.drop_index(
        "ix_workspace_deletion_jobs_workspace_status",
        table_name="workspace_deletion_jobs",
    )
    op.drop_table("workspace_deletion_jobs")
    op.drop_index(
        "ix_workspace_deletion_confirmations_token_hash",
        table_name="workspace_deletion_confirmations",
    )
    op.drop_index(
        "ix_workspace_deletion_confirmations_workspace",
        table_name="workspace_deletion_confirmations",
    )
    op.drop_table("workspace_deletion_confirmations")
    op.drop_index(
        "ix_managed_objects_object_key", table_name="managed_objects"
    )
    op.drop_index("ix_managed_objects_owner", table_name="managed_objects")
    op.drop_index(
        "ix_managed_objects_workspace_state_purge",
        table_name="managed_objects",
    )
    op.drop_table("managed_objects")
    op.drop_index(
        "ix_retention_policies_workspace_effective",
        table_name="retention_policies",
    )
    op.drop_table("retention_policies")
    op.drop_column("deleted_items", "status")
    op.drop_column("deleted_items", "deletion_reason")
    op.drop_column("deleted_items", "scheduled_purge_at")
    op.drop_column("workspaces", "deletion_version")
    op.drop_column("workspaces", "status")
