"""Freeze model configuration and provider contract on analysis runs.

Revision ID: 20260728_0029
Revises: 20260728_0028
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260728_0029"
down_revision: str | None = "20260728_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analysis_runs",
        sa.Column("model_config_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "model_config_version",
            sa.String(length=80),
            nullable=False,
            server_default="legacy",
        ),
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "model_provider",
            sa.String(length=80),
            nullable=False,
            server_default="legacy",
        ),
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "provider_contract_version",
            sa.String(length=80),
            nullable=False,
            server_default="legacy",
        ),
    )
    op.create_foreign_key(
        "fk_analysis_runs_model_config_id",
        "analysis_runs",
        "model_configs",
        ["model_config_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_analysis_runs_model_config_id",
        "analysis_runs",
        ["model_config_id"],
    )
    op.execute(
        sa.text(
            "UPDATE analysis_runs "
            "SET model_provider = 'mock', "
            "provider_contract_version = 'mock-structured-v1' "
            "WHERE model_version LIKE 'mock%'"
        )
    )
    op.alter_column(
        "analysis_runs",
        "model_provider",
        server_default=None,
    )
    op.alter_column(
        "analysis_runs",
        "provider_contract_version",
        server_default=None,
    )
    op.alter_column(
        "analysis_runs",
        "model_config_version",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_analysis_runs_model_config_id",
        table_name="analysis_runs",
    )
    op.drop_constraint(
        "fk_analysis_runs_model_config_id",
        "analysis_runs",
        type_="foreignkey",
    )
    op.drop_column("analysis_runs", "provider_contract_version")
    op.drop_column("analysis_runs", "model_config_version")
    op.drop_column("analysis_runs", "model_provider")
    op.drop_column("analysis_runs", "model_config_id")
