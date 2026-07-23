"""Add governed risk ingestion and embedding metadata.

Revision ID: 20260723_0018
Revises: 20260723_0017
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa


revision: str = "20260723_0018"
down_revision: str | None = "20260723_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

platform_type = sa.Enum(
    "douyin",
    "xiaohongshu",
    name="content_platform",
    native_enum=False,
)
embedding_scope_type = sa.Enum(
    "public",
    "private",
    name="risk_embedding_scope",
    native_enum=False,
)


def upgrade() -> None:
    op.execute(
        "CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public"
    )
    op.execute(
        "SELECT set_config("
        "'search_path', current_schema() || ', public', true"
        ")"
    )
    op.add_column(
        "risk_documents",
        sa.Column("file_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "risk_documents",
        sa.Column("mime_type", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "risk_documents",
        sa.Column("object_key", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "risk_documents",
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "risk_documents",
        sa.Column(
            "resolved_ips",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        "risk_documents",
        sa.Column(
            "untrusted_data",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "risk_documents",
        sa.Column(
            "redistribution_authorized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column(
        "risk_documents",
        "resolved_ips",
        server_default=None,
    )
    op.alter_column(
        "risk_documents",
        "untrusted_data",
        server_default=None,
    )
    op.alter_column(
        "risk_documents",
        "redistribution_authorized",
        server_default=None,
    )
    op.create_index(
        "ix_risk_documents_content_sha256",
        "risk_documents",
        ["content_sha256"],
    )

    op.create_table(
        "risk_chunk_embeddings",
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("platform", platform_type, nullable=False),
        sa.Column("scope", embedding_scope_type, nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column(
            "embedding_version",
            sa.String(length=80),
            nullable=False,
        ),
        sa.Column("vector", Vector(), nullable=False),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(scope = 'public' AND workspace_id IS NULL) OR "
            "(scope = 'private' AND workspace_id IS NOT NULL)",
            name="ck_risk_chunk_embeddings_scope_workspace",
        ),
        sa.CheckConstraint(
            "dimension > 0",
            name="ck_risk_chunk_embeddings_dimension",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["risk_chunks.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "chunk_id",
            name="uq_risk_chunk_embeddings_chunk_id",
        ),
    )
    op.create_index(
        "ix_risk_chunk_embeddings_workspace_id",
        "risk_chunk_embeddings",
        ["workspace_id"],
    )
    op.create_index(
        "ix_risk_chunk_embeddings_chunk_id",
        "risk_chunk_embeddings",
        ["chunk_id"],
    )
    op.create_index(
        "ix_risk_chunk_embeddings_platform",
        "risk_chunk_embeddings",
        ["platform"],
    )
    op.create_index(
        "ix_risk_chunk_embeddings_model",
        "risk_chunk_embeddings",
        ["workspace_id", "platform", "model_id", "embedding_version"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_risk_chunk_embeddings_model",
        table_name="risk_chunk_embeddings",
    )
    op.drop_index(
        "ix_risk_chunk_embeddings_platform",
        table_name="risk_chunk_embeddings",
    )
    op.drop_index(
        "ix_risk_chunk_embeddings_chunk_id",
        table_name="risk_chunk_embeddings",
    )
    op.drop_index(
        "ix_risk_chunk_embeddings_workspace_id",
        table_name="risk_chunk_embeddings",
    )
    op.drop_table("risk_chunk_embeddings")
    op.drop_index(
        "ix_risk_documents_content_sha256",
        table_name="risk_documents",
    )
    op.drop_column("risk_documents", "redistribution_authorized")
    op.drop_column("risk_documents", "untrusted_data")
    op.drop_column("risk_documents", "resolved_ips")
    op.drop_column("risk_documents", "content_sha256")
    op.drop_column("risk_documents", "object_key")
    op.drop_column("risk_documents", "mime_type")
    op.drop_column("risk_documents", "file_name")
