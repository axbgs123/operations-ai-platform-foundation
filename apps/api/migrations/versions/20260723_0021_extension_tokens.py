"""Add scoped short-lived extension tokens.

Revision ID: 20260723_0021
Revises: 20260723_0020
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260723_0021"
down_revision: str | None = "20260723_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "extension_tokens",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=120), nullable=False),
        sa.Column("exchange_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["member_id"], ["workspace_members.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exchange_fingerprint"),
    )
    op.create_index(
        "ix_extension_tokens_token_hash",
        "extension_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_extension_tokens_workspace_id",
        "extension_tokens",
        ["workspace_id"],
    )
    op.create_index(
        "ix_extension_tokens_member_id",
        "extension_tokens",
        ["member_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_extension_tokens_member_id", table_name="extension_tokens")
    op.drop_index(
        "ix_extension_tokens_workspace_id", table_name="extension_tokens"
    )
    op.drop_index("ix_extension_tokens_token_hash", table_name="extension_tokens")
    op.drop_table("extension_tokens")
