"""Add governed hotspot screenshot captures and confirmed snapshots.

Revision ID: 20260813_0043
Revises: 20260813_0042
Create Date: 2026-08-13
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260813_0043"
down_revision: str | None = "20260813_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

platform_type = sa.Enum(
    "douyin", "xiaohongshu", name="content_platform", native_enum=False
)
capture_status_type = sa.Enum(
    "queued",
    "running",
    "review_ready",
    "failed",
    "confirmed",
    "cancelled",
    name="hotspot_capture_status",
    native_enum=False,
)
capture_completeness_type = sa.Enum(
    "visible",
    "full_page_complete",
    "full_page_partial",
    name="hotspot_capture_completeness",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "hotspot_capture_tasks",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column("target_platform", platform_type, nullable=False),
        sa.Column("source_url", sa.String(length=2_000), nullable=False),
        sa.Column("source_host", sa.String(length=253), nullable=False),
        sa.Column("page_title", sa.String(length=300), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completeness", capture_completeness_type, nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("image_sha256", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=40), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", capture_status_type, nullable=False),
        sa.Column("candidate_entries", sa.JSON(), nullable=False),
        sa.Column("model_config_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("contract_version", sa.String(length=120), nullable=False),
        sa.Column("configuration_version", sa.String(length=100), nullable=False),
        sa.Column("region", sa.String(length=32), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("confirmed_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("confirmation_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("object_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "target_platform IN ('douyin', 'xiaohongshu')",
            name="ck_hotspot_capture_tasks_platform",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'review_ready', 'failed', 'confirmed', 'cancelled')",
            name="ck_hotspot_capture_tasks_status",
        ),
        sa.CheckConstraint(
            "completeness IN ('visible', 'full_page_complete', 'full_page_partial')",
            name="ck_hotspot_capture_tasks_completeness",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["member_id"], ["workspace_members.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["model_config_id"], ["model_configs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "member_id",
            "idempotency_key",
            name="uq_hotspot_capture_tasks_idempotency",
        ),
    )
    op.create_index(
        "ix_hotspot_capture_tasks_workspace",
        "hotspot_capture_tasks",
        ["workspace_id"],
    )
    op.create_table(
        "hotspot_snapshots",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("capture_task_id", sa.Uuid(), nullable=False),
        sa.Column("confirmed_by", sa.Uuid(), nullable=False),
        sa.Column("target_platform", platform_type, nullable=False),
        sa.Column("source_url", sa.String(length=2_000), nullable=False),
        sa.Column("source_host", sa.String(length=253), nullable=False),
        sa.Column("page_title", sa.String(length=300), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completeness", capture_completeness_type, nullable=False),
        sa.Column("ocr_model_id", sa.String(length=160), nullable=False),
        sa.Column("ocr_contract_version", sa.String(length=120), nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "target_platform IN ('douyin', 'xiaohongshu')",
            name="ck_hotspot_snapshots_platform",
        ),
        sa.CheckConstraint(
            "completeness IN ('visible', 'full_page_complete', 'full_page_partial')",
            name="ck_hotspot_snapshots_completeness",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["capture_task_id"],
            ["hotspot_capture_tasks.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"], ["workspace_members.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("capture_task_id"),
    )
    op.create_index(
        "ix_hotspot_snapshots_workspace",
        "hotspot_snapshots",
        ["workspace_id"],
    )
    op.create_index(
        "ix_hotspot_snapshots_workspace_platform",
        "hotspot_snapshots",
        ["workspace_id", "target_platform"],
    )
    op.create_table(
        "hotspot_entries",
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("topic", sa.String(length=300), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("heat", sa.String(length=80), nullable=True),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["hotspot_snapshots.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id",
            "position",
            name="uq_hotspot_entries_position",
        ),
    )
    op.create_index(
        "ix_hotspot_entries_snapshot",
        "hotspot_entries",
        ["snapshot_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_hotspot_entries_snapshot", table_name="hotspot_entries")
    op.drop_table("hotspot_entries")
    op.drop_index(
        "ix_hotspot_snapshots_workspace_platform",
        table_name="hotspot_snapshots",
    )
    op.drop_index(
        "ix_hotspot_snapshots_workspace", table_name="hotspot_snapshots"
    )
    op.drop_table("hotspot_snapshots")
    op.drop_index(
        "ix_hotspot_capture_tasks_workspace",
        table_name="hotspot_capture_tasks",
    )
    op.drop_table("hotspot_capture_tasks")
