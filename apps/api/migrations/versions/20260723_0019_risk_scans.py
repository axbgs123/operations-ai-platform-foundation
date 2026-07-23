"""Add immutable version-linked multimodal risk scans.

Revision ID: 20260723_0019
Revises: 20260723_0018
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260723_0019"
down_revision: str | None = "20260723_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "risk_scans",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("content_id", sa.Uuid(), nullable=False),
        sa.Column(
            "platform",
            sa.Enum(
                "douyin",
                "xiaohongshu",
                name="content_platform",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "node",
            sa.Enum(
                "after_ingestion",
                "after_generation",
                "before_publication",
                name="risk_scan_node",
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
                "cancelled",
                "retrying",
                name="risk_scan_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("rule_version", sa.String(length=160), nullable=False),
        sa.Column("evidence_version", sa.String(length=160), nullable=False),
        sa.Column("embedding_model_id", sa.String(length=160), nullable=False),
        sa.Column("embedding_version", sa.String(length=80), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("rag_model_version", sa.String(length=160), nullable=False),
        sa.Column("scanner_version", sa.String(length=160), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("diagnostics", sa.JSON(), nullable=False),
        sa.Column("cover_asset_id", sa.Uuid(), nullable=True),
        sa.Column("previous_scan_id", sa.Uuid(), nullable=True),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
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
            ["account_id"],
            ["platform_accounts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["contents.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cover_asset_id"],
            ["content_assets.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["previous_scan_id"],
            ["risk_scans.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["workspace_members.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_risk_scans_workspace_idempotency",
        ),
    )
    op.create_index(
        "ix_risk_scans_workspace_id",
        "risk_scans",
        ["workspace_id"],
    )
    op.create_index(
        "ix_risk_scans_account_id",
        "risk_scans",
        ["account_id"],
    )
    op.create_index(
        "ix_risk_scans_content_id",
        "risk_scans",
        ["content_id"],
    )
    op.create_index(
        "ix_risk_scans_previous_scan_id",
        "risk_scans",
        ["previous_scan_id"],
    )
    op.create_index(
        "ix_risk_scans_history",
        "risk_scans",
        ["workspace_id", "content_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_risk_scans_history", table_name="risk_scans")
    op.drop_index(
        "ix_risk_scans_previous_scan_id",
        table_name="risk_scans",
    )
    op.drop_index("ix_risk_scans_content_id", table_name="risk_scans")
    op.drop_index("ix_risk_scans_account_id", table_name="risk_scans")
    op.drop_index("ix_risk_scans_workspace_id", table_name="risk_scans")
    op.drop_table("risk_scans")
