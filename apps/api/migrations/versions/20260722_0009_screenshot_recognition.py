"""Add staged screenshot recognition fields.

Revision ID: 20260722_0009
Revises: 20260722_0008
Create Date: 2026-07-22
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0009"
down_revision: str | None = "20260722_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

recognition_status = sa.Enum(
    "pending",
    "processing",
    "ready",
    "failed",
    name="screenshot_recognition_status",
    native_enum=False,
)
source_kind = sa.Enum(
    "manual",
    "csv",
    "xlsx",
    "screenshot",
    name="import_source_kind",
    native_enum=False,
)
previous_source_kind = sa.Enum(
    "manual",
    "csv",
    "xlsx",
    name="import_source_kind",
    native_enum=False,
)


def upgrade() -> None:
    op.alter_column(
        "import_batches",
        "source_kind",
        existing_type=previous_source_kind,
        type_=source_kind,
        existing_nullable=False,
    )
    op.add_column(
        "import_batches",
        sa.Column("recognition_status", recognition_status, nullable=True),
    )
    op.add_column(
        "import_batches",
        sa.Column("recognition_error", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "import_batches",
        sa.Column("screenshot_mime_type", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "import_batches",
        sa.Column("screenshot_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "import_batches",
        sa.Column("screenshot_bytes", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "import_batches",
        sa.Column("screenshot_metadata", sa.JSON(), nullable=True),
    )
    op.add_column(
        "import_batches",
        sa.Column(
            "screenshot_retention_policy",
            sa.String(length=40),
            nullable=True,
        ),
    )
    op.add_column(
        "import_batches",
        sa.Column("recognition_output", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("import_batches", "recognition_output")
    op.drop_column("import_batches", "screenshot_retention_policy")
    op.drop_column("import_batches", "screenshot_metadata")
    op.drop_column("import_batches", "screenshot_bytes")
    op.drop_column("import_batches", "screenshot_sha256")
    op.drop_column("import_batches", "screenshot_mime_type")
    op.drop_column("import_batches", "recognition_error")
    op.drop_column("import_batches", "recognition_status")
    op.alter_column(
        "import_batches",
        "source_kind",
        existing_type=source_kind,
        type_=previous_source_kind,
        existing_nullable=False,
    )
