from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin, utc_now
from app.modules.content.account_models import Platform, platform_type
from app.modules.metrics.models import ContentType, content_type_enum


class ContentStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class AssetCategory(StrEnum):
    COVER = "cover"
    SCREENSHOT = "screenshot"
    REFERENCE_IMAGE = "reference_image"
    DOCUMENT = "document"


content_status_type = Enum(
    ContentStatus,
    name="content_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)
asset_category_type = Enum(
    AssetCategory,
    name="asset_category",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)


class Content(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "contents"
    __table_args__ = (
        Index("ix_contents_workspace_id", "workspace_id"),
        Index("ix_contents_account_id", "account_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform_accounts.id", ondelete="RESTRICT")
    )
    platform: Mapped[Platform] = mapped_column(platform_type)
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    objective_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("objective_profiles.id", ondelete="RESTRICT")
    )
    benchmark_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("benchmark_profiles.id", ondelete="RESTRICT")
    )
    content_type: Mapped[ContentType] = mapped_column(
        content_type_enum, default=ContentType.VIDEO
    )
    column_campaign_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("columns_campaigns.id", ondelete="SET NULL"), default=None
    )
    work_url: Mapped[str | None] = mapped_column(String(2048), default=None)
    status: Mapped[ContentStatus] = mapped_column(content_status_type, default=ContentStatus.DRAFT)
    published_title: Mapped[str | None] = mapped_column(String(300), default=None)
    published_body: Mapped[str | None] = mapped_column(Text, default=None)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)


class ContentAsset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "content_assets"
    __table_args__ = (
        Index("ix_content_assets_workspace_id", "workspace_id"),
        Index("ix_content_assets_content_id", "content_id"),
        Index("ix_content_assets_object_key", "object_key", unique=True),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    content_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contents.id", ondelete="CASCADE")
    )
    category: Mapped[AssetCategory] = mapped_column(asset_category_type)
    object_key: Mapped[str] = mapped_column(String(1024))
    file_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer)


class DeletedItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "deleted_items"
    __table_args__ = (
        Index("ix_deleted_items_workspace_id", "workspace_id"),
        Index("ix_deleted_items_resource", "resource_type", "resource_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    deleted_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspace_members.id", ondelete="SET NULL"), default=None
    )
    deleted_at: Mapped[datetime] = mapped_column(UTCDateTime(), default_factory=utc_now)
    restored_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
