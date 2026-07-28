from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UTCDateTime, UUIDPrimaryKeyMixin
from app.modules.content.account_models import Platform, platform_type


class CaptureTaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


capture_task_status_enum = Enum(
    CaptureTaskStatus,
    name="capture_task_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)


class CaptureTask(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "extension_capture_tasks"
    __table_args__ = (
        Index("ix_extension_capture_tasks_workspace_id", "workspace_id"),
        Index("ix_extension_capture_tasks_token_id", "token_id"),
        UniqueConstraint(
            "workspace_id",
            "token_id",
            "idempotency_key",
            name="uq_extension_capture_tasks_idempotency",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    token_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("extension_tokens.id", ondelete="CASCADE")
    )
    member_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspace_members.id", ondelete="CASCADE")
    )
    platform: Mapped[Platform] = mapped_column(platform_type)
    page_version: Mapped[str] = mapped_column(String(80))
    page_identifier: Mapped[str] = mapped_column(String(160))
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime())
    idempotency_key: Mapped[str] = mapped_column(String(160))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(String(300))
    review_url: Mapped[str] = mapped_column(String(300))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[CaptureTaskStatus] = mapped_column(capture_task_status_enum)
    formal_snapshot_ids: Mapped[list[str]] = mapped_column(JSON)
    recognition_output: Mapped[dict[str, object] | None] = mapped_column(JSON, default=None)
    model_config_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("model_configs.id", ondelete="RESTRICT"),
        default=None,
    )
    provider: Mapped[str] = mapped_column(String(80), default="mock")
    model_id: Mapped[str] = mapped_column(
        String(160), default="mock-vision-v1"
    )
    contract_version: Mapped[str] = mapped_column(
        String(80), default="mock-vision-v1"
    )
    config_version: Mapped[str] = mapped_column(
        String(80), default="mock-static-v1"
    )
    region: Mapped[str | None] = mapped_column(String(32), default=None)
    metric_labels: Mapped[dict[str, str]] = mapped_column(
        JSON, default_factory=dict
    )
    error_code: Mapped[str | None] = mapped_column(String(120), default=None)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    confirmed_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspace_members.id", ondelete="SET NULL"), default=None
    )
    operation_version: Mapped[int] = mapped_column(
        Integer,
        init=False,
        default=1,
    )
    __mapper_args__ = {"version_id_col": operation_version}
