"""Add workspace export jobs.

Revision ID: 20260726_0023
Revises: 20260723_0022
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260726_0023"
down_revision: str | None = "20260723_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "export_jobs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("csv", "markdown", name="export_kind", native_enum=False),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                name="export_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("content_id", sa.Uuid(), nullable=True),
        sa.Column("object_key", sa.String(length=1024), nullable=True),
        sa.Column("file_name", sa.String(length=180), nullable=True),
        sa.Column("mime_type", sa.String(length=120), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["workspace_members.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["content_id"], ["contents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "requested_by",
            "idempotency_key",
            name="uq_export_jobs_workspace_member_idempotency",
        ),
    )
    op.create_index(
        "ix_export_jobs_workspace_id",
        "export_jobs",
        ["workspace_id"],
    )
    op.create_index(
        "ix_export_jobs_requested_by",
        "export_jobs",
        ["requested_by"],
    )


def downgrade() -> None:
    op.drop_index("ix_export_jobs_requested_by", table_name="export_jobs")
    op.drop_index("ix_export_jobs_workspace_id", table_name="export_jobs")
    op.drop_table("export_jobs")
