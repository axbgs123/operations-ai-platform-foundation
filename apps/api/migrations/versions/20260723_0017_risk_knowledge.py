"""Add governed risk knowledge documents and chunks.

Revision ID: 20260723_0017
Revises: 20260723_0016
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_0017"
down_revision: str | None = "20260723_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

platform_type = sa.Enum(
    "douyin",
    "xiaohongshu",
    name="content_platform",
    native_enum=False,
)
scope_type = sa.Enum(
    "public",
    "private",
    name="risk_document_scope",
    native_enum=False,
)
source_level_type = sa.Enum(
    "S1",
    "S2",
    "S3",
    "S4",
    "S5",
    name="risk_source_level",
    native_enum=False,
)
authorization_status_type = sa.Enum(
    "not_required",
    "authorized",
    "unverified",
    "restricted",
    name="risk_authorization_status",
    native_enum=False,
)
document_status_type = sa.Enum(
    "draft",
    "parsed",
    "pending_review",
    "active",
    "superseded",
    "expired",
    name="risk_document_status",
    native_enum=False,
)
chunk_scope_type = sa.Enum(
    "public",
    "private",
    name="risk_chunk_scope",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "risk_documents",
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("platform", platform_type, nullable=False),
        sa.Column("scope", scope_type, nullable=False),
        sa.Column("source_level", source_level_type, nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column(
            "authorization_status",
            authorization_status_type,
            nullable=False,
        ),
        sa.Column("status", document_status_type, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column(
            "private_document_id",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "effective_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "accessed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("previous_version_id", sa.Uuid(), nullable=True),
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
            name="ck_risk_documents_scope_workspace",
        ),
        sa.CheckConstraint(
            "source_url IS NOT NULL OR private_document_id IS NOT NULL",
            name="ck_risk_documents_source_reference",
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_risk_documents_version",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["workspace_members.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["previous_version_id"],
            ["risk_documents.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "previous_version_id",
            name="uq_risk_documents_previous_version",
        ),
    )
    op.create_index(
        "ix_risk_documents_workspace_id",
        "risk_documents",
        ["workspace_id"],
    )
    op.create_index(
        "ix_risk_documents_platform",
        "risk_documents",
        ["platform"],
    )
    op.create_index(
        "ix_risk_documents_scope",
        "risk_documents",
        ["scope"],
    )
    op.create_index(
        "ix_risk_documents_status",
        "risk_documents",
        ["status"],
    )
    op.create_index(
        "ix_risk_documents_previous_version_id",
        "risk_documents",
        ["previous_version_id"],
    )
    op.create_index(
        "ix_risk_documents_current_lookup",
        "risk_documents",
        ["workspace_id", "platform", "status", "effective_at"],
    )

    op.create_table(
        "risk_chunks",
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("platform", platform_type, nullable=False),
        sa.Column("scope", chunk_scope_type, nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("source_location", sa.String(length=500), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
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
            name="ck_risk_chunks_scope_workspace",
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_risk_chunks_index",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["risk_documents.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_risk_chunks_document_index",
        ),
    )
    op.create_index(
        "ix_risk_chunks_workspace_id",
        "risk_chunks",
        ["workspace_id"],
    )
    op.create_index(
        "ix_risk_chunks_document_id",
        "risk_chunks",
        ["document_id"],
    )
    op.create_index(
        "ix_risk_chunks_platform",
        "risk_chunks",
        ["platform"],
    )


def downgrade() -> None:
    op.drop_index("ix_risk_chunks_platform", table_name="risk_chunks")
    op.drop_index("ix_risk_chunks_document_id", table_name="risk_chunks")
    op.drop_index("ix_risk_chunks_workspace_id", table_name="risk_chunks")
    op.drop_table("risk_chunks")
    op.drop_index(
        "ix_risk_documents_current_lookup",
        table_name="risk_documents",
    )
    op.drop_index(
        "ix_risk_documents_previous_version_id",
        table_name="risk_documents",
    )
    op.drop_index("ix_risk_documents_status", table_name="risk_documents")
    op.drop_index("ix_risk_documents_scope", table_name="risk_documents")
    op.drop_index("ix_risk_documents_platform", table_name="risk_documents")
    op.drop_index(
        "ix_risk_documents_workspace_id",
        table_name="risk_documents",
    )
    op.drop_table("risk_documents")
