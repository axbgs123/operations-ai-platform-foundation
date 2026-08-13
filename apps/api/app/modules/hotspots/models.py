from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UTCDateTime, UUIDPrimaryKeyMixin
from app.modules.content.account_models import Platform, platform_type


class HotspotCaptureStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    REVIEW_READY = "review_ready"
    FAILED = "failed"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class CaptureCompleteness(StrEnum):
    VISIBLE = "visible"
    FULL_PAGE_COMPLETE = "full_page_complete"
    FULL_PAGE_PARTIAL = "full_page_partial"


hotspot_capture_status_enum = Enum(
    HotspotCaptureStatus,
    name="hotspot_capture_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)

capture_completeness_enum = Enum(
    CaptureCompleteness,
    name="hotspot_capture_completeness",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)


class HotspotCaptureTask(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "hotspot_capture_tasks"
    __table_args__ = (
        Index("ix_hotspot_capture_tasks_workspace", "workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "member_id",
            "idempotency_key",
            name="uq_hotspot_capture_tasks_idempotency",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    member_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="CASCADE"),
    )
    target_platform: Mapped[Platform] = mapped_column(platform_type)
    source_url: Mapped[str] = mapped_column(String(2_000))
    source_host: Mapped[str] = mapped_column(String(253))
    page_title: Mapped[str] = mapped_column(String(300))
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime())
    completeness: Mapped[CaptureCompleteness] = mapped_column(
        capture_completeness_enum
    )
    idempotency_key: Mapped[str] = mapped_column(String(160))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    image_sha256: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(40))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[HotspotCaptureStatus] = mapped_column(
        hotspot_capture_status_enum
    )
    model_id: Mapped[str] = mapped_column(String(160))
    contract_version: Mapped[str] = mapped_column(String(120))
    configuration_version: Mapped[str] = mapped_column(String(100))
    candidate_entries: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, default_factory=list
    )
    model_config_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("model_configs.id", ondelete="RESTRICT"),
        default=None,
    )
    provider: Mapped[str] = mapped_column(String(80), default="mock")
    region: Mapped[str | None] = mapped_column(String(32), default=None)
    error_code: Mapped[str | None] = mapped_column(String(120), default=None)
    confirmed_snapshot_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), default=None
    )
    confirmation_fingerprint: Mapped[str | None] = mapped_column(
        String(64), default=None
    )
    object_deleted_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )


class HotspotSnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "hotspot_snapshots"
    __table_args__ = (
        Index("ix_hotspot_snapshots_workspace", "workspace_id"),
        Index(
            "ix_hotspot_snapshots_workspace_platform",
            "workspace_id",
            "target_platform",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    capture_task_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("hotspot_capture_tasks.id", ondelete="RESTRICT"),
        unique=True,
    )
    confirmed_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="RESTRICT"),
    )
    target_platform: Mapped[Platform] = mapped_column(platform_type)
    source_url: Mapped[str] = mapped_column(String(2_000))
    source_host: Mapped[str] = mapped_column(String(253))
    page_title: Mapped[str] = mapped_column(String(300))
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime())
    confirmed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    completeness: Mapped[CaptureCompleteness] = mapped_column(
        capture_completeness_enum
    )
    ocr_model_id: Mapped[str] = mapped_column(String(160))
    ocr_contract_version: Mapped[str] = mapped_column(String(120))
    entry_count: Mapped[int] = mapped_column(Integer)


class HotspotEntry(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "hotspot_entries"
    __table_args__ = (
        Index("ix_hotspot_entries_snapshot", "snapshot_id"),
        UniqueConstraint(
            "snapshot_id",
            "position",
            name="uq_hotspot_entries_position",
        ),
    )

    snapshot_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("hotspot_snapshots.id", ondelete="CASCADE"),
    )
    position: Mapped[int] = mapped_column(Integer)
    topic: Mapped[str] = mapped_column(String(300))
    rank: Mapped[int | None] = mapped_column(Integer, default=None)
    heat: Mapped[str | None] = mapped_column(String(80), default=None)
    selected: Mapped[bool] = mapped_column(Boolean, default=True)
