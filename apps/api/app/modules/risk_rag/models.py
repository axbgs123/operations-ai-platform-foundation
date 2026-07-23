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


class RiskScanStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class RiskScanNode(StrEnum):
    AFTER_INGESTION = "after_ingestion"
    AFTER_GENERATION = "after_generation"
    BEFORE_PUBLICATION = "before_publication"


class RiskFeedbackType(StrEnum):
    CORRECT = "correct"
    FALSE_POSITIVE = "false_positive"
    MISSED = "missed"
    OUTDATED_RULE = "outdated_rule"
    WRONG_SEVERITY = "wrong_severity"


class RiskFeedbackStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class RiskFeedbackEventType(StrEnum):
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class ImmutableRiskScanError(RuntimeError):
    pass


class ImmutableRiskFeedbackEventError(RuntimeError):
    pass


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


class RiskScan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "risk_scans"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_risk_scans_workspace_idempotency",
        ),
        Index("ix_risk_scans_workspace_id", "workspace_id"),
        Index("ix_risk_scans_account_id", "account_id"),
        Index("ix_risk_scans_content_id", "content_id"),
        Index("ix_risk_scans_previous_scan_id", "previous_scan_id"),
        Index(
            "ix_risk_scans_history",
            "workspace_id",
            "content_id",
            "created_at",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform_accounts.id", ondelete="RESTRICT"),
    )
    content_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("contents.id", ondelete="RESTRICT"),
    )
    platform: Mapped[Platform] = mapped_column(platform_type)
    node: Mapped[RiskScanNode] = mapped_column(
        enum_type(RiskScanNode, "risk_scan_node")
    )
    status: Mapped[RiskScanStatus] = mapped_column(
        enum_type(RiskScanStatus, "risk_scan_status")
    )
    idempotency_key: Mapped[str] = mapped_column(String(200))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    input_snapshot: Mapped[dict[str, object]] = mapped_column(JSON)
    rule_version: Mapped[str] = mapped_column(String(160))
    evidence_version: Mapped[str] = mapped_column(String(160))
    embedding_model_id: Mapped[str] = mapped_column(String(160))
    embedding_version: Mapped[str] = mapped_column(String(80))
    embedding_dimension: Mapped[int] = mapped_column(Integer)
    rag_model_version: Mapped[str] = mapped_column(String(160))
    scanner_version: Mapped[str] = mapped_column(String(160))
    result: Mapped[dict[str, object] | None] = mapped_column(
        JSON,
        default=None,
    )
    error_code: Mapped[str | None] = mapped_column(
        String(120),
        default=None,
    )
    diagnostics: Mapped[list[str]] = mapped_column(
        JSON,
        default_factory=list,
    )
    cover_asset_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("content_assets.id", ondelete="RESTRICT"),
        default=None,
    )
    previous_scan_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("risk_scans.id", ondelete="RESTRICT"),
        default=None,
    )
    requested_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )


class RiskScanFeedback(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "risk_scan_feedback"
    __table_args__ = (
        Index("ix_risk_scan_feedback_workspace_id", "workspace_id"),
        Index("ix_risk_scan_feedback_scan_id", "scan_id"),
        Index(
            "ix_risk_scan_feedback_review_queue",
            "workspace_id",
            "status",
            "created_at",
        ),
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_risk_scan_feedback_workspace_idempotency",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    scan_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("risk_scans.id", ondelete="RESTRICT"),
    )
    platform: Mapped[Platform] = mapped_column(platform_type)
    feedback_type: Mapped[RiskFeedbackType] = mapped_column(
        enum_type(RiskFeedbackType, "risk_feedback_type")
    )
    status: Mapped[RiskFeedbackStatus] = mapped_column(
        enum_type(RiskFeedbackStatus, "risk_feedback_status")
    )
    idempotency_key: Mapped[str] = mapped_column(String(200))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    finding_reference: Mapped[str] = mapped_column(String(160))
    rule_version: Mapped[str] = mapped_column(String(160))
    evidence_version: Mapped[str] = mapped_column(String(160))
    submitted_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
    )
    comment: Mapped[str | None] = mapped_column(Text, default=None)
    comment_untrusted_data: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
    )
    reviewed_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        default=None,
    )
    review_note: Mapped[str | None] = mapped_column(Text, default=None)


class RiskFeedbackEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "risk_feedback_events"
    __table_args__ = (
        Index("ix_risk_feedback_events_workspace_id", "workspace_id"),
        Index("ix_risk_feedback_events_feedback_id", "feedback_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    feedback_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("risk_scan_feedback.id", ondelete="RESTRICT"),
    )
    event_type: Mapped[RiskFeedbackEventType] = mapped_column(
        enum_type(RiskFeedbackEventType, "risk_feedback_event_type")
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
    )
    safe_note: Mapped[str | None] = mapped_column(String(500), default=None)


@event.listens_for(RiskScan, "before_update")
def _reject_risk_scan_update(mapper, connection, target) -> None:
    raise ImmutableRiskScanError("persisted risk scans are immutable")


@event.listens_for(RiskScan, "before_delete")
def _reject_risk_scan_delete(mapper, connection, target) -> None:
    raise ImmutableRiskScanError("persisted risk scans cannot be deleted")


@event.listens_for(RiskFeedbackEvent, "before_update")
def _reject_risk_feedback_event_update(mapper, connection, target) -> None:
    raise ImmutableRiskFeedbackEventError(
        "risk feedback history is append-only"
    )


@event.listens_for(RiskFeedbackEvent, "before_delete")
def _reject_risk_feedback_event_delete(mapper, connection, target) -> None:
    raise ImmutableRiskFeedbackEventError(
        "risk feedback history cannot be deleted"
    )
