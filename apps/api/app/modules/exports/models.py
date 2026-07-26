from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class ExportKind(StrEnum):
    CSV = "csv"
    MARKDOWN = "markdown"


class ExportStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
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
