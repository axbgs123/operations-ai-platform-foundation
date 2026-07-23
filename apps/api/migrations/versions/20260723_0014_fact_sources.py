"""Add traceable fact sources and candidate items.

Revision ID: 20260723_0014
Revises: 20260722_0013
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_0014"
down_revision: str | None = "20260722_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

fact_source_kind = sa.Enum(
    "document", "image", "link", "text", "web", name="fact_source_kind", native_enum=False
)
fact_source_level = sa.Enum(
    "L1", "L2", "L3", "L4", "L5", name="fact_source_level", native_enum=False
)
fact_source_status = sa.Enum(
    "parsed",
    "awaiting_fetch",
    "awaiting_model",
    "failed",
    name="fact_source_status",
    native_enum=False,
)
fact_item_status = sa.Enum(
    "candidate", "confirmed", name="fact_item_status", native_enum=False
)
fact_conflict_status = sa.Enum(
    "clear", "unresolved", "resolved", name="fact_conflict_status", native_enum=False
)


def upgrade() -> None:
    op.create_table(
        "fact_sources",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", fact_source_kind, nullable=False),
        sa.Column("level", fact_source_level, nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("status", fact_source_status, nullable=False),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("workspace_members.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("resolved_ips", sa.JSON(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=160), nullable=True),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("raw_content", sa.LargeBinary(), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("untrusted_data", sa.Boolean(), nullable=False),
        sa.Column("status_detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_fact_sources_workspace_id", "fact_sources", ["workspace_id"])
    op.create_index("ix_fact_sources_kind", "fact_sources", ["kind"])
    op.create_index("ix_fact_sources_status", "fact_sources", ["status"])
    op.create_table(
        "fact_items",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.Uuid(),
            sa.ForeignKey("fact_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field_name", sa.String(length=120), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("source_location", sa.String(length=500), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", fact_item_status, nullable=False),
        sa.Column("conflict_status", fact_conflict_status, nullable=False),
        sa.Column(
            "confirmed_by",
            sa.Uuid(),
            sa.ForeignKey("workspace_members.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("override_record", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_fact_items_workspace_id", "fact_items", ["workspace_id"])
    op.create_index("ix_fact_items_source_id", "fact_items", ["source_id"])
    op.create_index("ix_fact_items_status", "fact_items", ["status"])
    op.create_index(
        "ix_fact_items_conflict_status", "fact_items", ["conflict_status"]
    )


def downgrade() -> None:
    op.drop_index("ix_fact_items_conflict_status", table_name="fact_items")
    op.drop_index("ix_fact_items_status", table_name="fact_items")
    op.drop_index("ix_fact_items_source_id", table_name="fact_items")
    op.drop_index("ix_fact_items_workspace_id", table_name="fact_items")
    op.drop_table("fact_items")
    op.drop_index("ix_fact_sources_status", table_name="fact_sources")
    op.drop_index("ix_fact_sources_kind", table_name="fact_sources")
    op.drop_index("ix_fact_sources_workspace_id", table_name="fact_sources")
    op.drop_table("fact_sources")
