"""Track configuration-bound native web-search verification.

Revision ID: 20260813_0042
Revises: 20260812_0041
Create Date: 2026-08-13
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260813_0042"
down_revision: str | None = "20260812_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_configs",
        sa.Column(
            "native_web_search_status",
            sa.String(length=24),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "model_configs",
        sa.Column(
            "native_web_search_checked_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "model_configs",
        sa.Column(
            "native_web_search_contract_version", sa.String(length=120), nullable=True
        ),
    )
    op.add_column(
        "model_configs",
        sa.Column(
            "native_web_search_configuration_version",
            sa.String(length=100),
            nullable=True,
        ),
    )
    op.add_column(
        "model_configs",
        sa.Column(
            "native_web_search_safe_error_code", sa.String(length=80), nullable=True
        ),
    )
    op.create_check_constraint(
        "ck_model_configs_native_web_search_status",
        "model_configs",
        "native_web_search_status IN ('unknown', 'supported', 'unsupported', 'failed')",
    )
    op.alter_column("model_configs", "native_web_search_status", server_default=None)


def downgrade() -> None:
    op.drop_constraint(
        "ck_model_configs_native_web_search_status",
        "model_configs",
        type_="check",
    )
    op.drop_column("model_configs", "native_web_search_safe_error_code")
    op.drop_column("model_configs", "native_web_search_configuration_version")
    op.drop_column("model_configs", "native_web_search_contract_version")
    op.drop_column("model_configs", "native_web_search_checked_at")
    op.drop_column("model_configs", "native_web_search_status")
