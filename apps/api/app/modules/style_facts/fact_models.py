from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    Enum,
    Float,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class FactSourceKind(StrEnum):
    DOCUMENT = "document"
    IMAGE = "image"
    LINK = "link"
    TEXT = "text"
    WEB = "web"


class FactSourceLevel(StrEnum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"


class FactSourceStatus(StrEnum):
    PARSED = "parsed"
    AWAITING_FETCH = "awaiting_fetch"
    AWAITING_MODEL = "awaiting_model"
    FAILED = "failed"


class FactItemStatus(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"


class FactConflictStatus(StrEnum):
    CLEAR = "clear"
    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"


def enum_type(enum: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum,
        name=name,
        native_enum=False,
        values_callable=lambda members: [member.value for member in members],
    )


class FactSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "fact_sources"
    __table_args__ = (
        Index("ix_fact_sources_workspace_id", "workspace_id"),
        Index("ix_fact_sources_kind", "kind"),
        Index("ix_fact_sources_status", "status"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    kind: Mapped[FactSourceKind] = mapped_column(
        enum_type(FactSourceKind, "fact_source_kind")
    )
    level: Mapped[FactSourceLevel] = mapped_column(
        enum_type(FactSourceLevel, "fact_source_level")
    )
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[FactSourceStatus] = mapped_column(
        enum_type(FactSourceStatus, "fact_source_status")
    )
    created_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )
    source_url: Mapped[str | None] = mapped_column(String(2048), default=None)
    resolved_ips: Mapped[list[str]] = mapped_column(JSON, default_factory=list)
    file_name: Mapped[str | None] = mapped_column(String(255), default=None)
    mime_type: Mapped[str | None] = mapped_column(String(160), default=None)
    size: Mapped[int | None] = mapped_column(default=None)
    content_sha256: Mapped[str | None] = mapped_column(String(64), default=None)
    raw_content: Mapped[bytes | None] = mapped_column(LargeBinary, default=None)
    source_text: Mapped[str | None] = mapped_column(Text, default=None)
    published_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
    accessed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
    untrusted_data: Mapped[bool] = mapped_column(Boolean, default=True)
    status_detail: Mapped[dict[str, object]] = mapped_column(
        JSON, default_factory=dict
    )


class FactItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "fact_items"
    __table_args__ = (
        Index("ix_fact_items_workspace_id", "workspace_id"),
        Index("ix_fact_items_source_id", "source_id"),
        Index("ix_fact_items_field_code", "field_code"),
        Index("ix_fact_items_status", "status"),
        Index("ix_fact_items_conflict_status", "conflict_status"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    source_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("fact_sources.id", ondelete="CASCADE")
    )
    field_name: Mapped[str] = mapped_column(String(120))
    field_code: Mapped[str] = mapped_column(String(160))
    value: Mapped[str] = mapped_column(Text)
    source_location: Mapped[str] = mapped_column(String(500))
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[FactItemStatus] = mapped_column(
        enum_type(FactItemStatus, "fact_item_status")
    )
    conflict_status: Mapped[FactConflictStatus] = mapped_column(
        enum_type(FactConflictStatus, "fact_conflict_status"),
        default=FactConflictStatus.CLEAR,
    )
    confirmed_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
    override_record: Mapped[dict[str, object] | None] = mapped_column(
        JSON, default=None
    )
