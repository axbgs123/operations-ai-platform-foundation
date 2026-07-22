"""Add encrypted workspace model configurations.

Revision ID: 20260722_0012
Revises: 20260722_0011
Create Date: 2026-07-22
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0012"
down_revision: str | None = "20260722_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

model_config_status = sa.Enum(
    "verified",
    "experimental",
    "community",
    "incompatible",
    name="model_config_status",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "model_configs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("status", model_config_status, nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("encryption_key_version", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "provider",
            "model_id",
            name="uq_model_config_workspace_provider_model",
        ),
    )
    op.create_index(
        "ix_model_configs_workspace_id",
        "model_configs",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_model_configs_workspace_id", table_name="model_configs")
    op.drop_table("model_configs")
