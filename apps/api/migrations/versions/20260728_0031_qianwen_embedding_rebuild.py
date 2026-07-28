"""Add fenced blue-green RiskRAG embedding generations.

Revision ID: 20260728_0031
Revises: 20260728_0030
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260728_0031"
down_revision: str | None = "20260728_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "risk_chunk_embeddings",
        sa.Column(
            "provider",
            sa.String(length=80),
            nullable=False,
            server_default="mock",
        ),
    )
    op.add_column(
        "risk_chunk_embeddings",
        sa.Column("model_config_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "risk_chunk_embeddings",
        sa.Column(
            "contract_version",
            sa.String(length=80),
            nullable=False,
            server_default="legacy",
        ),
    )
    op.add_column(
        "risk_chunk_embeddings",
        sa.Column(
            "config_version",
            sa.String(length=100),
            nullable=False,
            server_default="legacy",
        ),
    )
    op.add_column(
        "risk_chunk_embeddings",
        sa.Column(
            "index_generation",
            sa.String(length=64),
            nullable=False,
            server_default="legacy",
        ),
    )
    op.add_column(
        "risk_chunk_embeddings",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.create_foreign_key(
        "fk_risk_chunk_embeddings_model_config_id",
        "risk_chunk_embeddings",
        "model_configs",
        ["model_config_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "uq_risk_chunk_embeddings_chunk_id",
        "risk_chunk_embeddings",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_risk_chunk_embeddings_generation",
        "risk_chunk_embeddings",
        [
            "chunk_id",
            "model_id",
            "contract_version",
            "dimension",
            "index_generation",
        ],
    )

    op.alter_column(
        "knowledge_index_rebuilds",
        "restore_job_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )
    for name, type_ in (
        ("model_config_id", sa.Uuid()),
        ("provider", sa.String(length=80)),
        ("region", sa.String(length=32)),
        ("contract_version", sa.String(length=80)),
        ("config_version", sa.String(length=100)),
        ("index_generation", sa.String(length=64)),
        ("idempotency_key", sa.String(length=200)),
        ("claim_token", sa.String(length=64)),
        ("lease_expires_at", sa.DateTime(timezone=True)),
        ("chunk_manifest_digest", sa.String(length=64)),
        ("activated_at", sa.DateTime(timezone=True)),
    ):
        op.add_column(
            "knowledge_index_rebuilds",
            sa.Column(name, type_, nullable=True),
        )
    for name in ("total_chunks", "completed_chunks", "attempt_count"):
        op.add_column(
            "knowledge_index_rebuilds",
            sa.Column(
                name,
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )
    op.add_column(
        "knowledge_index_rebuilds",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "knowledge_index_rebuilds",
        sa.Column(
            "operation_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.execute(
        sa.text(
            "UPDATE knowledge_index_rebuilds "
            "SET index_generation = CAST(id AS VARCHAR), "
            "idempotency_key = 'restore:' || CAST(restore_job_id AS VARCHAR) "
            "|| ':' || CAST(platform AS VARCHAR)"
        )
    )
    op.alter_column(
        "knowledge_index_rebuilds",
        "index_generation",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.alter_column(
        "knowledge_index_rebuilds",
        "idempotency_key",
        existing_type=sa.String(length=200),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_knowledge_index_rebuilds_model_config_id",
        "knowledge_index_rebuilds",
        "model_configs",
        ["model_config_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_knowledge_index_rebuild_workspace_platform_idempotency",
        "knowledge_index_rebuilds",
        ["workspace_id", "platform", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_knowledge_index_rebuild_workspace_platform_idempotency",
        "knowledge_index_rebuilds",
        type_="unique",
    )
    op.drop_constraint(
        "fk_knowledge_index_rebuilds_model_config_id",
        "knowledge_index_rebuilds",
        type_="foreignkey",
    )
    for name in (
        "operation_version",
        "activated_at",
        "is_active",
        "chunk_manifest_digest",
        "lease_expires_at",
        "claim_token",
        "attempt_count",
        "completed_chunks",
        "total_chunks",
        "idempotency_key",
        "index_generation",
        "config_version",
        "contract_version",
        "region",
        "provider",
        "model_config_id",
    ):
        op.drop_column("knowledge_index_rebuilds", name)
    op.alter_column(
        "knowledge_index_rebuilds",
        "restore_job_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )

    op.drop_constraint(
        "uq_risk_chunk_embeddings_generation",
        "risk_chunk_embeddings",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_risk_chunk_embeddings_chunk_id",
        "risk_chunk_embeddings",
        ["chunk_id"],
    )
    op.drop_constraint(
        "fk_risk_chunk_embeddings_model_config_id",
        "risk_chunk_embeddings",
        type_="foreignkey",
    )
    for name in (
        "is_active",
        "index_generation",
        "config_version",
        "contract_version",
        "model_config_id",
        "provider",
    ):
        op.drop_column("risk_chunk_embeddings", name)
