"""Add full restore and knowledge index rebuild jobs.

Revision ID: 20260726_0024
Revises: 20260726_0023
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260726_0024"
down_revision: str | None = "20260726_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "restore_jobs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("target_workspace_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("archive_sha256", sa.String(length=64), nullable=False),
        sa.Column("archive_object_key", sa.String(length=1024), nullable=False),
        sa.Column("staging_prefix", sa.String(length=1024), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                "retrying",
                "cancelled",
                name="full_restore_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "phase",
            sa.Enum(
                "uploaded",
                "validating",
                "preview_ready",
                "database",
                "moving_objects",
                "rebuilding_index",
                "completed",
                "failed",
                "compensation_required",
                name="full_restore_phase",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("preview_id", sa.String(length=64), nullable=False),
        sa.Column(
            "manifest_fingerprint",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("preview_json", sa.JSON(), nullable=False),
        sa.Column("object_plan", sa.JSON(), nullable=False),
        sa.Column(
            "confirm_idempotency_key",
            sa.String(length=200),
            nullable=True,
        ),
        sa.Column("claim_token", sa.String(length=64), nullable=True),
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column(
            "knowledge_index_message",
            sa.String(length=160),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["workspace_members.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "requested_by",
            "idempotency_key",
            name="uq_restore_jobs_workspace_member_idempotency",
        ),
    )
    op.create_index(
        "ix_restore_jobs_workspace_id",
        "restore_jobs",
        ["workspace_id"],
    )
    op.create_index(
        "ix_restore_jobs_requested_by",
        "restore_jobs",
        ["requested_by"],
    )

    op.create_table(
        "knowledge_index_rebuilds",
        sa.Column("restore_job_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column(
            "platform",
            sa.Enum(
                "douyin",
                "xiaohongshu",
                name="platform",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                "configuration_required",
                name="knowledge_index_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("model_id", sa.String(length=160), nullable=True),
        sa.Column(
            "embedding_version",
            sa.String(length=80),
            nullable=True,
        ),
        sa.Column("dimension", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["restore_job_id"],
            ["restore_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "restore_job_id",
            "platform",
            name="uq_knowledge_index_rebuild_restore_platform",
        ),
    )
    op.create_index(
        "ix_knowledge_index_rebuilds_workspace_id",
        "knowledge_index_rebuilds",
        ["workspace_id"],
    )
    op.create_index(
        "ix_knowledge_index_rebuilds_restore_job_id",
        "knowledge_index_rebuilds",
        ["restore_job_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_index_rebuilds_restore_job_id",
        table_name="knowledge_index_rebuilds",
    )
    op.drop_index(
        "ix_knowledge_index_rebuilds_workspace_id",
        table_name="knowledge_index_rebuilds",
    )
    op.drop_table("knowledge_index_rebuilds")
    op.drop_index(
        "ix_restore_jobs_requested_by",
        table_name="restore_jobs",
    )
    op.drop_index(
        "ix_restore_jobs_workspace_id",
        table_name="restore_jobs",
    )
    op.drop_table("restore_jobs")
