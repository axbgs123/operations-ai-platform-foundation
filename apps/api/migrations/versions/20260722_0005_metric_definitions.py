"""Create workspace metric definitions.

Revision ID: 20260722_0005
Revises: 20260721_0004
Create Date: 2026-07-22
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0005"
down_revision: str | None = "20260721_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

platform_type = sa.Enum(
    "douyin", "xiaohongshu", name="content_platform", native_enum=False
)
content_type = sa.Enum(
    "video", "image_text", name="metric_content_type", native_enum=False
)
metric_unit = sa.Enum(
    "count", "ratio", "seconds", "number", name="metric_unit", native_enum=False
)
metric_aggregation = sa.Enum(
    "latest", "sum", "average", name="metric_aggregation", native_enum=False
)


def upgrade() -> None:
    op.create_table(
        "metric_definitions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", platform_type, nullable=False),
        sa.Column("content_type", content_type, nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("unit", metric_unit, nullable=False),
        sa.Column("aggregation", metric_aggregation, nullable=False),
        sa.Column("higher_is_better", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "platform",
            "content_type",
            "key",
            name="uq_metric_definition_scope_key",
        ),
    )
    op.create_index(
        "ix_metric_definitions_workspace_id",
        "metric_definitions",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_table("metric_definitions")
