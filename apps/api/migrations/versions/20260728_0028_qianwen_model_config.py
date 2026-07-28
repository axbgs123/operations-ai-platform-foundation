"""Add controlled Qianwen endpoint fields to model configs.

Revision ID: 20260728_0028
Revises: 20260727_0027
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260728_0028"
down_revision: str | None = "20260727_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_configs",
        sa.Column("region", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "model_configs",
        sa.Column(
            "provider_workspace_id",
            sa.String(length=80),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_model_configs_qianwen_endpoint_fields",
        "model_configs",
        "provider <> 'qianwen' OR "
        "(region IS NOT NULL AND provider_workspace_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_model_configs_qianwen_endpoint_fields",
        "model_configs",
        type_="check",
    )
    op.drop_column("model_configs", "provider_workspace_id")
    op.drop_column("model_configs", "region")
