from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    JSON,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin
from app.modules.content.account_models import Platform, platform_type


class ExportKind(StrEnum):
    CSV = "csv"
    MARKDOWN = "markdown"
    JSON = "json"
    ZIP = "zip"


class ExportStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class FullRestoreStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class FullRestorePhase(StrEnum):
    UPLOADED = "uploaded"
    VALIDATING = "validating"
    PREVIEW_READY = "preview_ready"
    DATABASE = "database"
    MOVING_OBJECTS = "moving_objects"
    REBUILDING_INDEX = "rebuilding_index"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATION_REQUIRED = "compensation_required"


class KnowledgeIndexStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CONFIGURATION_REQUIRED = "configuration_required"


export_kind_enum = Enum(
    ExportKind,
    name="export_kind",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)
export_status_enum = Enum(
    ExportStatus,
    name="export_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)
full_restore_status_enum = Enum(
    FullRestoreStatus,
    name="full_restore_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)
full_restore_phase_enum = Enum(
    FullRestorePhase,
    name="full_restore_phase",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)
knowledge_index_status_enum = Enum(
    KnowledgeIndexStatus,
    name="knowledge_index_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)


class ExportTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "export_jobs"
    __table_args__ = (
        Index("ix_export_jobs_workspace_id", "workspace_id"),
        Index("ix_export_jobs_requested_by", "requested_by"),
        UniqueConstraint(
            "workspace_id",
            "requested_by",
            "idempotency_key",
            name="uq_export_jobs_workspace_member_idempotency",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    requested_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="CASCADE"),
    )
    kind: Mapped[ExportKind] = mapped_column(export_kind_enum)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[ExportStatus] = mapped_column(export_status_enum)
    content_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("contents.id", ondelete="CASCADE"),
        default=None,
    )
    object_key: Mapped[str | None] = mapped_column(String(1024), default=None)
    file_name: Mapped[str | None] = mapped_column(String(180), default=None)
    mime_type: Mapped[str | None] = mapped_column(String(120), default=None)
    error_code: Mapped[str | None] = mapped_column(String(80), default=None)
    enqueued_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
    claim_token: Mapped[str | None] = mapped_column(String(64), default=None)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)


class RestoreJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "restore_jobs"
    __table_args__ = (
        Index("ix_restore_jobs_workspace_id", "workspace_id"),
        Index("ix_restore_jobs_requested_by", "requested_by"),
        UniqueConstraint(
            "workspace_id",
            "requested_by",
            "idempotency_key",
            name="uq_restore_jobs_workspace_member_idempotency",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    requested_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="CASCADE"),
    )
    target_workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    mode: Mapped[str] = mapped_column(String(20))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    archive_sha256: Mapped[str] = mapped_column(String(64))
    archive_object_key: Mapped[str] = mapped_column(String(1024))
    staging_prefix: Mapped[str] = mapped_column(String(1024))
    status: Mapped[FullRestoreStatus] = mapped_column(
        full_restore_status_enum
    )
    phase: Mapped[FullRestorePhase] = mapped_column(full_restore_phase_enum)
    preview_id: Mapped[str] = mapped_column(String(64))
    manifest_fingerprint: Mapped[str] = mapped_column(String(64))
    preview_json: Mapped[dict[str, object]] = mapped_column(JSON)
    object_plan: Mapped[list[dict[str, object]]] = mapped_column(JSON)
    confirm_idempotency_key: Mapped[str | None] = mapped_column(
        String(200), default=None
    )
    claim_token: Mapped[str | None] = mapped_column(
        String(64), default=None
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
    error_code: Mapped[str | None] = mapped_column(String(80), default=None)
    knowledge_index_message: Mapped[str | None] = mapped_column(
        String(160), default=None
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )


class KnowledgeIndexRebuild(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_index_rebuilds"
    __table_args__ = (
        UniqueConstraint(
            "restore_job_id",
            "platform",
            name="uq_knowledge_index_rebuild_restore_platform",
        ),
        Index(
            "ix_knowledge_index_rebuilds_workspace_id",
            "workspace_id",
        ),
        Index(
            "ix_knowledge_index_rebuilds_restore_job_id",
            "restore_job_id",
        ),
    )

    restore_job_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("restore_jobs.id", ondelete="CASCADE"),
    )
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    platform: Mapped[Platform] = mapped_column(platform_type)
    status: Mapped[KnowledgeIndexStatus] = mapped_column(
        knowledge_index_status_enum
    )
    model_id: Mapped[str | None] = mapped_column(String(160), default=None)
    embedding_version: Mapped[str | None] = mapped_column(
        String(80), default=None
    )
    dimension: Mapped[int | None] = mapped_column(Integer, default=None)
    error_code: Mapped[str | None] = mapped_column(String(80), default=None)
