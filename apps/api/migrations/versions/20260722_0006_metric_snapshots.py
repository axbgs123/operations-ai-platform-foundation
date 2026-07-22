"""Create append-only metric snapshots and transactional outbox.

Revision ID: 20260722_0006
Revises: 20260722_0005
Create Date: 2026-07-22
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0006"
down_revision: str | None = "20260722_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

platform_type = sa.Enum(
    "douyin", "xiaohongshu", name="content_platform", native_enum=False
)
content_type = sa.Enum(
    "video", "image_text", name="metric_content_type", native_enum=False
)
snapshot_source = sa.Enum(
    "manual",
    "tabular_import",
    "screenshot",
    "extension",
    name="snapshot_source",
    native_enum=False,
)


def upgrade() -> None:
    op.add_column(
        "contents",
        sa.Column(
            "content_type",
            content_type,
            nullable=False,
            server_default="video",
        ),
    )
    op.alter_column("contents", "content_type", server_default=None)

    op.create_table(
        "data_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "content_id",
            sa.Uuid(),
            sa.ForeignKey("contents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("platform_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", platform_type, nullable=False),
        sa.Column("content_type", content_type, nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("age_seconds", sa.Integer(), nullable=False),
        sa.Column("maturity_bucket", sa.String(length=8), nullable=False),
        sa.Column("source", snapshot_source, nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "confirmed_by",
            sa.Uuid(),
            sa.ForeignKey("workspace_members.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "original_screenshot_asset_id",
            sa.Uuid(),
            sa.ForeignKey("content_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_data_snapshots_workspace_id", "data_snapshots", ["workspace_id"])
    op.create_index("ix_data_snapshots_content_id", "data_snapshots", ["content_id"])

    op.create_table(
        "snapshot_metric_values",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("data_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric_key", sa.String(length=80), nullable=False),
        sa.Column("raw_value", sa.Numeric(24, 6), nullable=True),
        sa.Column("normalized_value", sa.Numeric(24, 6), nullable=True),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column("eligible_for_benchmark", sa.Boolean(), nullable=False),
        sa.Column(
            "metric_definition_id",
            sa.Uuid(),
            sa.ForeignKey("metric_definitions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "snapshot_id", "metric_key", name="uq_snapshot_metric_key"
        ),
    )
    op.create_index(
        "ix_snapshot_metric_values_workspace_id",
        "snapshot_metric_values",
        ["workspace_id"],
    )
    op.create_index(
        "ix_snapshot_metric_values_snapshot_id",
        "snapshot_metric_values",
        ["snapshot_id"],
    )

    op.create_table(
        "metric_outbox_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_metric_outbox_idempotency_key"
        ),
    )
    op.create_index(
        "ix_metric_outbox_events_workspace_id",
        "metric_outbox_events",
        ["workspace_id"],
    )
    op.create_index(
        "ix_metric_outbox_events_processed_at",
        "metric_outbox_events",
        ["processed_at"],
    )


def downgrade() -> None:
    op.drop_table("metric_outbox_events")
    op.drop_table("snapshot_metric_values")
    op.drop_table("data_snapshots")
    op.drop_column("contents", "content_type")
