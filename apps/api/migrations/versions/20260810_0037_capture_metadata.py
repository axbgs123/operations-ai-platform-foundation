"""Persist bounded extension capture metadata.

Revision ID: 20260810_0037
Revises: 20260810_0036
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260810_0037"
down_revision: str | None = "20260810_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "extension_capture_tasks",
        sa.Column(
            "capture_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("extension_capture_tasks", "capture_metadata")
