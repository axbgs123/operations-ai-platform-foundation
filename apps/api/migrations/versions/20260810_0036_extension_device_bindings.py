"""Add persistent extension device bindings.

Revision ID: 20260810_0036
Revises: 20260810_0035
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260810_0036"
down_revision: str | None = "20260810_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "extension_device_bindings",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("public_key_jwk", sa.JSON(), nullable=False),
        sa.Column("public_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("extension_version", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
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
        "ix_extension_device_bindings_device_id",
        "extension_device_bindings",
        ["device_id"],
        unique=True,
    )
    op.create_index(
        "ix_extension_device_bindings_workspace_id",
        "extension_device_bindings",
        ["workspace_id"],
    )
    op.create_index(
        "ix_extension_device_bindings_member_id",
        "extension_device_bindings",
        ["member_id"],
    )
    op.create_index(
        "ix_extension_device_bindings_public_key_fingerprint",
        "extension_device_bindings",
        ["public_key_fingerprint"],
        unique=True,
    )
    op.add_column(
        "extension_tokens",
        sa.Column("device_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_extension_tokens_device_id_extension_device_bindings",
        "extension_tokens",
        "extension_device_bindings",
        ["device_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_extension_tokens_device_id",
        "extension_tokens",
        ["device_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_extension_tokens_device_id", table_name="extension_tokens")
    op.drop_constraint(
        "fk_extension_tokens_device_id_extension_device_bindings",
        "extension_tokens",
        type_="foreignkey",
    )
    op.drop_column("extension_tokens", "device_id")
    op.drop_index(
        "ix_extension_device_bindings_public_key_fingerprint",
        table_name="extension_device_bindings",
    )
    op.drop_index(
        "ix_extension_device_bindings_member_id",
        table_name="extension_device_bindings",
    )
    op.drop_index(
        "ix_extension_device_bindings_workspace_id",
        table_name="extension_device_bindings",
    )
    op.drop_index(
        "ix_extension_device_bindings_device_id",
        table_name="extension_device_bindings",
    )
    op.drop_table("extension_device_bindings")
