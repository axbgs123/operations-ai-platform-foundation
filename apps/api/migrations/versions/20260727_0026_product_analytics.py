"""Add versioned, privacy-minimal product analytics.

Revision ID: 20260727_0026
Revises: 20260727_0025
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260727_0026"
down_revision: str | None = "20260727_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    platform = sa.Enum(
        "douyin",
        "xiaohongshu",
        name="content_platform",
        native_enum=False,
    )
    op.add_column(
        "product_events",
        sa.Column(
            "event_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column("product_events", sa.Column("platform", platform))
    for column, target in (
        ("account_id", "platform_accounts.id"),
        ("content_id", "contents.id"),
        ("analysis_run_id", "analysis_runs.id"),
        ("generation_run_id", "text_generation_runs.id"),
        ("suggestion_id", "analysis_suggestions.id"),
    ):
        op.add_column("product_events", sa.Column(column, sa.Uuid()))
        op.create_foreign_key(
            f"fk_product_events_{column}",
            "product_events",
            target.split(".")[0],
            [column],
            [target.split(".")[1]],
            ondelete="CASCADE",
        )
    op.add_column(
        "product_events",
        sa.Column("idempotency_key", sa.String(length=200)),
    )
    op.add_column(
        "product_events",
        sa.Column("payload_fingerprint", sa.String(length=64)),
    )
    op.add_column(
        "product_events",
        sa.Column(
            "provider_mode",
            sa.String(length=20),
            nullable=False,
            server_default="real",
        ),
    )
    op.add_column(
        "product_events",
        sa.Column(
            "analytics_eligible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.execute(
        "UPDATE product_events SET "
        "idempotency_key = 'legacy:' || CAST(id AS VARCHAR), "
        "payload_fingerprint = repeat('0', 64)"
    )
    op.alter_column("product_events", "idempotency_key", nullable=False)
    op.alter_column(
        "product_events",
        "payload_fingerprint",
        nullable=False,
    )
    op.alter_column("product_events", "event_version", server_default=None)
    op.alter_column("product_events", "provider_mode", server_default=None)
    op.alter_column(
        "product_events",
        "analytics_eligible",
        server_default=None,
    )
    op.create_unique_constraint(
        "uq_product_events_workspace_idempotency",
        "product_events",
        ["workspace_id", "idempotency_key"],
    )
    op.create_index(
        "ix_product_events_workspace_name_time",
        "product_events",
        ["workspace_id", "event_name", "occurred_at"],
    )
    op.create_index(
        "ix_product_events_analysis_run_id",
        "product_events",
        ["analysis_run_id"],
    )
    op.create_index(
        "ix_product_events_generation_run_id",
        "product_events",
        ["generation_run_id"],
    )

    op.create_table(
        "product_event_outbox",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("payload_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("event_id", sa.Uuid()),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("error_code", sa.String(length=80)),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["product_events.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_product_event_outbox_workspace_idempotency",
        ),
    )
    op.create_index(
        "ix_product_event_outbox_pending",
        "product_event_outbox",
        ["processed_at", "created_at"],
    )

    op.add_column(
        "data_snapshots",
        sa.Column(
            "analytics_eligible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.alter_column(
        "data_snapshots",
        "analytics_eligible",
        server_default=None,
    )
    op.add_column(
        "text_generation_runs",
        sa.Column(
            "modification_algorithm_version",
            sa.String(length=80),
            nullable=False,
            server_default="normalized-levenshtein-v1",
        ),
    )
    op.alter_column(
        "text_generation_runs",
        "modification_algorithm_version",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column(
        "text_generation_runs",
        "modification_algorithm_version",
    )
    op.drop_column("data_snapshots", "analytics_eligible")
    op.drop_index(
        "ix_product_event_outbox_pending",
        table_name="product_event_outbox",
    )
    op.drop_table("product_event_outbox")
    op.drop_index(
        "ix_product_events_generation_run_id",
        table_name="product_events",
    )
    op.drop_index(
        "ix_product_events_analysis_run_id",
        table_name="product_events",
    )
    op.drop_index(
        "ix_product_events_workspace_name_time",
        table_name="product_events",
    )
    op.drop_constraint(
        "uq_product_events_workspace_idempotency",
        "product_events",
        type_="unique",
    )
    for column in (
        "suggestion_id",
        "generation_run_id",
        "analysis_run_id",
        "content_id",
        "account_id",
    ):
        op.drop_constraint(
            f"fk_product_events_{column}",
            "product_events",
            type_="foreignkey",
        )
        op.drop_column("product_events", column)
    for column in (
        "analytics_eligible",
        "provider_mode",
        "payload_fingerprint",
        "idempotency_key",
        "platform",
        "event_version",
    ):
        op.drop_column("product_events", column)
