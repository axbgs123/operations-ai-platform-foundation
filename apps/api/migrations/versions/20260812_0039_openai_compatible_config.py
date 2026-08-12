"""Add private OpenAI-compatible text provider configuration.

Revision ID: 20260812_0039
Revises: 20260812_0038
Create Date: 2026-08-12
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260812_0039"
down_revision: str | None = "20260812_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_configs",
        sa.Column("display_name", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "model_configs",
        sa.Column("endpoint_base_url", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_model_configs_openai_compatible_fields",
        "model_configs",
        "provider <> 'openai_compatible' OR "
        "(display_name IS NOT NULL AND endpoint_base_url IS NOT NULL "
        "AND region IS NULL AND provider_workspace_id IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_model_configs_openai_compatible_fields",
        "model_configs",
        type_="check",
    )
    op.drop_column("model_configs", "endpoint_base_url")
    op.drop_column("model_configs", "display_name")
