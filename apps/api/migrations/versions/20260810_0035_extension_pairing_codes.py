"""Add one-time extension pairing codes.

Revision ID: 20260810_0035
Revises: 20260805_0034
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260810_0035"
down_revision: str | None = "20260805_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "extension_pairing_codes",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column("code_digest", sa.String(length=64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["member_id"], ["workspace_members.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_extension_pairing_codes_code_digest",
        "extension_pairing_codes",
        ["code_digest"],
        unique=True,
    )
    op.create_index(
        "ix_extension_pairing_codes_workspace_id",
        "extension_pairing_codes",
        ["workspace_id"],
    )
    op.create_index(
        "ix_extension_pairing_codes_member_id",
        "extension_pairing_codes",
        ["member_id"],
    )


def downgrade() -> None:
    op.drop_table("extension_pairing_codes")
