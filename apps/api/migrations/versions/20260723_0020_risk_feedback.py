"""Add governed version-linked risk feedback and append-only review history.

Revision ID: 20260723_0020
Revises: 20260723_0019
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260723_0020"
down_revision: str | None = "20260723_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "risk_scan_feedback",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
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
            "feedback_type",
            sa.Enum(
                "correct",
                "false_positive",
                "missed",
                "outdated_rule",
                "wrong_severity",
                name="risk_feedback_type",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending_review",
                "approved",
                "rejected",
                "withdrawn",
                name="risk_feedback_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("finding_reference", sa.String(length=160), nullable=False),
        sa.Column("rule_version", sa.String(length=160), nullable=False),
        sa.Column("evidence_version", sa.String(length=160), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "comment_untrusted_data",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scan_id"],
            ["risk_scans.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"],
            ["workspace_members.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["workspace_members.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_risk_scan_feedback_workspace_idempotency",
        ),
    )
    op.create_index(
        "ix_risk_scan_feedback_workspace_id",
        "risk_scan_feedback",
        ["workspace_id"],
    )
    op.create_index(
        "ix_risk_scan_feedback_scan_id",
        "risk_scan_feedback",
        ["scan_id"],
    )
    op.create_index(
        "ix_risk_scan_feedback_review_queue",
        "risk_scan_feedback",
        ["workspace_id", "status", "created_at"],
    )
    op.create_table(
        "risk_feedback_events",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("feedback_id", sa.Uuid(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "submitted",
                "approved",
                "rejected",
                "withdrawn",
                name="risk_feedback_event_type",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("safe_note", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["feedback_id"],
            ["risk_scan_feedback.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["workspace_members.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_risk_feedback_events_workspace_id",
        "risk_feedback_events",
        ["workspace_id"],
    )
    op.create_index(
        "ix_risk_feedback_events_feedback_id",
        "risk_feedback_events",
        ["feedback_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_risk_feedback_events_feedback_id",
        table_name="risk_feedback_events",
    )
    op.drop_index(
        "ix_risk_feedback_events_workspace_id",
        table_name="risk_feedback_events",
    )
    op.drop_table("risk_feedback_events")
    op.drop_index(
        "ix_risk_scan_feedback_review_queue",
        table_name="risk_scan_feedback",
    )
    op.drop_index(
        "ix_risk_scan_feedback_scan_id",
        table_name="risk_scan_feedback",
    )
    op.drop_index(
        "ix_risk_scan_feedback_workspace_id",
        table_name="risk_scan_feedback",
    )
    op.drop_table("risk_scan_feedback")
