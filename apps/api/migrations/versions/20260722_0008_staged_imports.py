"""Create staged manual and tabular imports.

Revision ID: 20260722_0008
Revises: 20260722_0007
Create Date: 2026-07-22
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0008"
down_revision: str | None = "20260722_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

platform_type = sa.Enum(
    "douyin", "xiaohongshu", name="content_platform", native_enum=False
)
content_type = sa.Enum(
    "video", "image_text", name="metric_content_type", native_enum=False
)
source_kind = sa.Enum(
    "manual", "csv", "xlsx", name="import_source_kind", native_enum=False
)
batch_status = sa.Enum(
    "preview", "confirmed", name="import_batch_status", native_enum=False
)
row_status = sa.Enum(
    "new",
    "update",
    "suspected_duplicate",
    "failed",
    name="import_row_status",
    native_enum=False,
)


def upgrade() -> None:
    op.add_column(
        "contents",
        sa.Column("platform_content_id", sa.String(length=255), nullable=True),
    )
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
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
        sa.Column("source_kind", source_kind, nullable=False),
        sa.Column("status", batch_status, nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("header_mappings", sa.JSON(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "confirmed_by",
            sa.Uuid(),
            sa.ForeignKey("workspace_members.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("confirmation_result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_import_batches_workspace_id", "import_batches", ["workspace_id"]
    )
    op.create_index(
        "ix_import_batches_account_id", "import_batches", ["account_id"]
    )
    op.create_table(
        "import_rows",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "batch_id",
            sa.Uuid(),
            sa.ForeignKey("import_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw_data", sa.JSON(), nullable=False),
        sa.Column("normalized_data", sa.JSON(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.Column("status", row_status, nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column(
            "matched_content_id",
            sa.Uuid(),
            sa.ForeignKey("contents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("dedupe_reason", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_import_rows_workspace_id", "import_rows", ["workspace_id"])
    op.create_index("ix_import_rows_batch_id", "import_rows", ["batch_id"])


def downgrade() -> None:
    op.drop_table("import_rows")
    op.drop_table("import_batches")
    op.drop_column("contents", "platform_content_id")
