"""Create workspace isolation foundation.

Revision ID: 20260721_0001
Revises:
Create Date: 2026-07-21
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260721_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


member_role = sa.Enum(
    "admin",
    "editor",
    "viewer",
    "demo",
    name="workspace_member_role",
    native_enum=False,
)


def uuid_pk() -> sa.Column:
    return sa.Column("id", sa.Uuid(), primary_key=True, nullable=False)


def timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "workspaces",
        uuid_pk(),
        sa.Column("name", sa.String(length=120), nullable=False),
        *timestamps(),
    )
    op.create_table(
        "workspace_members",
        uuid_pk(),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("role", member_role, nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
    )
    op.create_index(
        "ix_workspace_members_workspace_id",
        "workspace_members",
        ["workspace_id"],
    )
    op.create_table(
        "workspace_access_codes",
        uuid_pk(),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("role", member_role, nullable=False),
        sa.Column(
            "member_id",
            sa.Uuid(),
            sa.ForeignKey("workspace_members.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
    )
    op.create_index(
        "ix_access_codes_workspace_id",
        "workspace_access_codes",
        ["workspace_id"],
    )
    op.create_table(
        "audit_logs",
        uuid_pk(),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column(
            "member_id",
            sa.Uuid(),
            sa.ForeignKey("workspace_members.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_workspace_id", "audit_logs", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_workspace_id", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_access_codes_workspace_id", table_name="workspace_access_codes")
    op.drop_table("workspace_access_codes")
    op.drop_index(
        "ix_workspace_members_workspace_id",
        table_name="workspace_members",
    )
    op.drop_table("workspace_members")
    op.drop_table("workspaces")
