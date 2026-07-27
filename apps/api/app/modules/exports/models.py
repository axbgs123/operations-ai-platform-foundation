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


class RetentionStrategy(StrEnum):
    IMMEDIATE = "immediate"
    SCHEDULED = "scheduled"
    EVIDENCE = "evidence"


class ManagedObjectState(StrEnum):
    ACTIVE = "active"
    SCHEDULED = "scheduled"
    EVIDENCE = "evidence"
    REFERENCED = "referenced"
    RETRYING = "retrying"
    DELETED = "deleted"


class WorkspaceDeletionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class WorkspaceDeletionPhase(StrEnum):
    PENDING = "pending"
    INVENTORY_CREATED = "inventory_created"
    ACCESS_REVOKED = "access_revoked"
    JOBS_CANCELLED = "jobs_cancelled"
    VECTORS_DELETED = "vectors_deleted"
    OBJECTS_DELETING = "objects_deleting"
    OBJECTS_DELETED = "objects_deleted"
    CACHES_DELETING = "caches_deleting"
    CACHES_DELETED = "caches_deleted"
    STRUCTURED_DATA_DELETING = "structured_data_deleting"
    STRUCTURED_DATA_DELETED = "structured_data_deleted"
    COMPLETED = "completed"
    FAILED = "failed"


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
retention_strategy_enum = Enum(
    RetentionStrategy,
    name="retention_strategy",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)
managed_object_state_enum = Enum(
    ManagedObjectState,
    name="managed_object_state",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)
workspace_deletion_status_enum = Enum(
    WorkspaceDeletionStatus,
    name="workspace_deletion_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)
workspace_deletion_phase_enum = Enum(
    WorkspaceDeletionPhase,
    name="workspace_deletion_phase",
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


class RetentionPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "retention_policies"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "version",
            name="uq_retention_policies_workspace_version",
        ),
        Index(
            "ix_retention_policies_workspace_effective",
            "workspace_id",
            "effective_at",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    version: Mapped[int] = mapped_column(Integer)
    strategy: Mapped[RetentionStrategy] = mapped_column(
        retention_strategy_enum
    )
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    retention_seconds: Mapped[int | None] = mapped_column(
        Integer, default=None
    )
    created_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )


class ManagedObject(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "managed_objects"
    __table_args__ = (
        Index(
            "ix_managed_objects_workspace_state_purge",
            "workspace_id",
            "state",
            "purge_at",
        ),
        Index(
            "ix_managed_objects_owner",
            "workspace_id",
            "owner_type",
            "owner_id",
        ),
        Index(
            "ix_managed_objects_object_key",
            "object_key",
            unique=True,
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    owner_type: Mapped[str] = mapped_column(String(80))
    owner_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    managed_prefix: Mapped[str] = mapped_column(String(1024))
    policy_version: Mapped[int] = mapped_column(Integer)
    strategy: Mapped[RetentionStrategy] = mapped_column(
        retention_strategy_enum
    )
    state: Mapped[ManagedObjectState] = mapped_column(
        managed_object_state_enum
    )
    object_key: Mapped[str | None] = mapped_column(
        String(1024), default=None
    )
    purge_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
    evidence_reason: Mapped[str | None] = mapped_column(
        String(240), default=None
    )
    related_resource_type: Mapped[str | None] = mapped_column(
        String(80), default=None
    )
    related_resource_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), default=None
    )
    claim_token: Mapped[str | None] = mapped_column(
        String(64), default=None
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(
        String(80), default=None
    )


class WorkspaceDeletionConfirmation(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "workspace_deletion_confirmations"
    __table_args__ = (
        Index(
            "ix_workspace_deletion_confirmations_workspace",
            "workspace_id",
            "expires_at",
        ),
        Index(
            "ix_workspace_deletion_confirmations_token_hash",
            "token_hash",
            unique=True,
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    requested_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    action: Mapped[str] = mapped_column(String(80))
    workspace_version: Mapped[int] = mapped_column(Integer)
    token_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    used_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )


class WorkspaceDeletionJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_deletion_jobs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "requested_by",
            "idempotency_key",
            name="uq_workspace_deletion_jobs_idempotency",
        ),
        Index(
            "ix_workspace_deletion_jobs_workspace_status",
            "workspace_id",
            "status",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    requested_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    inventory: Mapped[dict[str, object]] = mapped_column(JSON)
    status: Mapped[WorkspaceDeletionStatus] = mapped_column(
        workspace_deletion_status_enum
    )
    phase: Mapped[WorkspaceDeletionPhase] = mapped_column(
        workspace_deletion_phase_enum
    )
    claim_token: Mapped[str | None] = mapped_column(
        String(64), default=None
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
    error_code: Mapped[str | None] = mapped_column(
        String(80), default=None
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )


class DeletionAudit(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "deletion_audits"
    __table_args__ = (
        Index(
            "ix_deletion_audits_workspace_time",
            "workspace_id",
            "created_at",
        ),
        Index(
            "ix_deletion_audits_job",
            "deletion_job_id",
            "created_at",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    operation: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(100))
    phase: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    actor_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), default=None
    )
    deletion_job_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), default=None
    )
    resource_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), default=None
    )
    error_code: Mapped[str | None] = mapped_column(
        String(80), default=None
    )
