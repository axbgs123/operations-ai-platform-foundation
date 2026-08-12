"""Mark provider usage whose price is not known to the application.

Revision ID: 20260812_0040
Revises: 20260812_0039
Create Date: 2026-08-12
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260812_0040"
down_revision: str | None = "20260812_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_usage_reservations",
        sa.Column(
            "cost_known",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "model_usage_attempts",
        sa.Column(
            "cost_known",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("model_usage_attempts", "cost_known")
    op.drop_column("model_usage_reservations", "cost_known")
