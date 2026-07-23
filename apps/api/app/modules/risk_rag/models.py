from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql.base import ischema_names
from pgvector.sqlalchemy import Vector

from app.core.database import (
    Base,
    TimestampMixin,
    UTCDateTime,
    UUIDPrimaryKeyMixin,
)
from app.modules.content.account_models import Platform, platform_type


ischema_names["public.vector"] = Vector


@event.listens_for(Base.metadata, "before_create")
def _prepare_pgvector_extension(
    target,
    connection,
    **kwargs,
) -> None:
    if connection.dialect.name != "postgresql":
        return
    connection.execute(
        text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
    )
    connection.execute(
        text(
            "SELECT set_config("
            "'search_path', current_schema() || ', public', true"
            ")"
        )
    )


class RiskSourceLevel(StrEnum):
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"
    S4 = "S4"
    S5 = "S5"


class RiskDocumentScope(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"


class RiskAuthorizationStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    AUTHORIZED = "authorized"
    UNVERIFIED = "unverified"
    RESTRICTED = "restricted"


class RiskDocumentStatus(StrEnum):
    DRAFT = "draft"
    PARSED = "parsed"
    PENDING_REVIEW = "pending_review"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"


def enum_type(enum: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum,
        name=name,
        native_enum=False,
        values_callable=lambda members: [member.value for member in members],
    )


class RiskDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "risk_documents"
    __table_args__ = (
        CheckConstraint(
            "(scope = 'public' AND workspace_id IS NULL) OR "
            "(scope = 'private' AND workspace_id IS NOT NULL)",
            name="ck_risk_documents_scope_workspace",
        ),
        CheckConstraint(
            "source_url IS NOT NULL OR private_document_id IS NOT NULL",
            name="ck_risk_documents_source_reference",
        ),
        CheckConstraint("version > 0", name="ck_risk_documents_version"),
        UniqueConstraint(
            "previous_version_id",
            name="uq_risk_documents_previous_version",
        ),
        Index("ix_risk_documents_workspace_id", "workspace_id"),
        Index("ix_risk_documents_platform", "platform"),
        Index("ix_risk_documents_scope", "scope"),
        Index("ix_risk_documents_status", "status"),
        Index("ix_risk_documents_previous_version_id", "previous_version_id"),
        Index("ix_risk_documents_content_sha256", "content_sha256"),
        Index(
            "ix_risk_documents_current_lookup",
            "workspace_id",
            "platform",
            "status",
            "effective_at",
        ),
    )

    workspace_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    platform: Mapped[Platform] = mapped_column(platform_type)
    scope: Mapped[RiskDocumentScope] = mapped_column(
        enum_type(RiskDocumentScope, "risk_document_scope")
    )
    source_level: Mapped[RiskSourceLevel] = mapped_column(
        enum_type(RiskSourceLevel, "risk_source_level")
    )
    title: Mapped[str] = mapped_column(String(300))
    authorization_status: Mapped[RiskAuthorizationStatus] = mapped_column(
        enum_type(RiskAuthorizationStatus, "risk_authorization_status")
    )
    status: Mapped[RiskDocumentStatus] = mapped_column(
        enum_type(RiskDocumentStatus, "risk_document_status")
    )
    version: Mapped[int] = mapped_column(Integer)
    source_url: Mapped[str | None] = mapped_column(String(2048), default=None)
    private_document_id: Mapped[str | None] = mapped_column(
        String(255), default=None
    )
    published_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
    effective_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
    accessed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
    reviewed_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )
    previous_version_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("risk_documents.id", ondelete="RESTRICT"),
        default=None,
    )
    file_name: Mapped[str | None] = mapped_column(String(255), default=None)
    mime_type: Mapped[str | None] = mapped_column(String(160), default=None)
    object_key: Mapped[str | None] = mapped_column(String(1024), default=None)
    content_sha256: Mapped[str | None] = mapped_column(
        String(64), default=None
    )
    resolved_ips: Mapped[list[str]] = mapped_column(
        JSON,
        default_factory=list,
    )
    untrusted_data: Mapped[bool] = mapped_column(Boolean, default=True)
    redistribution_authorized: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )


class RiskChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "risk_chunks"
    __table_args__ = (
        CheckConstraint(
            "(scope = 'public' AND workspace_id IS NULL) OR "
            "(scope = 'private' AND workspace_id IS NOT NULL)",
            name="ck_risk_chunks_scope_workspace",
        ),
        CheckConstraint("chunk_index >= 0", name="ck_risk_chunks_index"),
        UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_risk_chunks_document_index",
        ),
        Index("ix_risk_chunks_workspace_id", "workspace_id"),
        Index("ix_risk_chunks_document_id", "document_id"),
        Index("ix_risk_chunks_platform", "platform"),
    )

    workspace_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("risk_documents.id", ondelete="CASCADE"),
    )
    platform: Mapped[Platform] = mapped_column(platform_type)
    scope: Mapped[RiskDocumentScope] = mapped_column(
        enum_type(RiskDocumentScope, "risk_chunk_scope")
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    source_location: Mapped[str] = mapped_column(String(500))
    text: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSON,
        default_factory=dict,
    )


class RiskChunkEmbedding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "risk_chunk_embeddings"
    __table_args__ = (
        CheckConstraint(
            "(scope = 'public' AND workspace_id IS NULL) OR "
            "(scope = 'private' AND workspace_id IS NOT NULL)",
            name="ck_risk_chunk_embeddings_scope_workspace",
        ),
        CheckConstraint(
            "dimension > 0",
            name="ck_risk_chunk_embeddings_dimension",
        ),
        UniqueConstraint(
            "chunk_id",
            name="uq_risk_chunk_embeddings_chunk_id",
        ),
        Index("ix_risk_chunk_embeddings_workspace_id", "workspace_id"),
        Index("ix_risk_chunk_embeddings_chunk_id", "chunk_id"),
        Index("ix_risk_chunk_embeddings_platform", "platform"),
        Index(
            "ix_risk_chunk_embeddings_model",
            "workspace_id",
            "platform",
            "model_id",
            "embedding_version",
        ),
    )

    workspace_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    chunk_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("risk_chunks.id", ondelete="CASCADE"),
    )
    platform: Mapped[Platform] = mapped_column(platform_type)
    scope: Mapped[RiskDocumentScope] = mapped_column(
        enum_type(RiskDocumentScope, "risk_embedding_scope")
    )
    model_id: Mapped[str] = mapped_column(String(160))
    dimension: Mapped[int] = mapped_column(Integer)
    embedding_version: Mapped[str] = mapped_column(String(80))
    vector: Mapped[list[float]] = mapped_column(Vector())
