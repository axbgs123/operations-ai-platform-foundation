from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin
from app.modules.content.account_models import Platform, platform_type
from app.modules.metrics.models import ContentType, content_type_enum


class ImportSourceKind(StrEnum):
    MANUAL = "manual"
    CSV = "csv"
    XLSX = "xlsx"
    SCREENSHOT = "screenshot"


class ScreenshotRecognitionStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ImportBatchStatus(StrEnum):
    PREVIEW = "preview"
    CONFIRMED = "confirmed"


class ImportRowStatus(StrEnum):
    NEW = "new"
    UPDATE = "update"
    SUSPECTED_DUPLICATE = "suspected_duplicate"
    FAILED = "failed"


class ExtensionTokenScope(StrEnum):
    CAPTURE_CREATE = "capture:create"
    CAPTURE_UPLOAD = "capture:upload"
    CAPTURE_READ = "capture:read"
    CONFIRM_SNAPSHOT = "snapshot:confirm"


import_source_kind_enum = Enum(
    ImportSourceKind,
    name="import_source_kind",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)
import_batch_status_enum = Enum(
    ImportBatchStatus,
    name="import_batch_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)
import_row_status_enum = Enum(
    ImportRowStatus,
    name="import_row_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)
screenshot_recognition_status_enum = Enum(
    ScreenshotRecognitionStatus,
    name="screenshot_recognition_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)


class ImportBatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        Index("ix_import_batches_workspace_id", "workspace_id"),
        Index("ix_import_batches_account_id", "account_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform_accounts.id", ondelete="CASCADE")
    )
    platform: Mapped[Platform] = mapped_column(platform_type)
    content_type: Mapped[ContentType] = mapped_column(content_type_enum)
    source_kind: Mapped[ImportSourceKind] = mapped_column(import_source_kind_enum)
    status: Mapped[ImportBatchStatus] = mapped_column(
        import_batch_status_enum, default=ImportBatchStatus.PREVIEW
    )
    file_name: Mapped[str | None] = mapped_column(String(255), default=None)
    header_mappings: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, default_factory=list
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    confirmed_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )
    confirmation_result: Mapped[dict[str, object] | None] = mapped_column(
        JSON, default=None
    )
    recognition_status: Mapped[ScreenshotRecognitionStatus | None] = mapped_column(
        screenshot_recognition_status_enum, default=None
    )
    recognition_error: Mapped[str | None] = mapped_column(String(500), default=None)
    screenshot_mime_type: Mapped[str | None] = mapped_column(String(120), default=None)
    screenshot_sha256: Mapped[str | None] = mapped_column(String(64), default=None)
    screenshot_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, default=None)
    screenshot_metadata: Mapped[dict[str, object] | None] = mapped_column(
        JSON, default=None
    )
    screenshot_retention_policy: Mapped[str | None] = mapped_column(
        String(40), default=None
    )
    recognition_output: Mapped[dict[str, object] | None] = mapped_column(
        JSON, default=None
    )


class ImportRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "import_rows"
    __table_args__ = (
        Index("ix_import_rows_workspace_id", "workspace_id"),
        Index("ix_import_rows_batch_id", "batch_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    batch_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("import_batches.id", ondelete="CASCADE")
    )
    row_number: Mapped[int] = mapped_column(Integer)
    raw_data: Mapped[dict[str, object]] = mapped_column(JSON)
    normalized_data: Mapped[dict[str, object]] = mapped_column(JSON)
    errors: Mapped[list[dict[str, str]]] = mapped_column(JSON)
    status: Mapped[ImportRowStatus] = mapped_column(import_row_status_enum)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    matched_content_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("contents.id", ondelete="SET NULL"),
        default=None,
    )
    dedupe_reason: Mapped[str | None] = mapped_column(String(80), default=None)


class ExtensionToken(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "extension_tokens"
    __table_args__ = (
        Index("ix_extension_tokens_token_hash", "token_hash", unique=True),
        Index("ix_extension_tokens_workspace_id", "workspace_id"),
        Index("ix_extension_tokens_member_id", "member_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    member_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspace_members.id", ondelete="CASCADE")
    )
    token_hash: Mapped[str] = mapped_column(String(64))
    client_id: Mapped[str] = mapped_column(String(120))
    exchange_fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list[str]] = mapped_column(JSON)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
