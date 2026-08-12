"""Allow the official global Qianwen AI Platform endpoint.

Revision ID: 20260812_0038
Revises: 20260810_0037
Create Date: 2026-08-12
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260812_0038"
down_revision: str | None = "20260810_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_model_configs_qianwen_endpoint_fields",
        "model_configs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_model_configs_qianwen_endpoint_fields",
        "model_configs",
        "provider <> 'qianwen' OR region IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_model_configs_qianwen_endpoint_fields",
        "model_configs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_model_configs_qianwen_endpoint_fields",
        "model_configs",
        "provider <> 'qianwen' OR "
        "(region IS NOT NULL AND provider_workspace_id IS NOT NULL)",
    )
