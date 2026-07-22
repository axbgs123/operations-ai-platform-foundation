from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import JSON, Enum, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin, utc_now


class StyleProfileStatus(StrEnum):
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"


style_profile_status_type = Enum(
    StyleProfileStatus,
    name="style_profile_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)


class StyleSample(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "style_samples"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "scope_key",
            "content_id",
            name="uq_style_sample_account_scope_content",
        ),
        Index("ix_style_samples_workspace_id", "workspace_id"),
        Index("ix_style_samples_account_id", "account_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform_accounts.id", ondelete="CASCADE")
    )
    scope_key: Mapped[str] = mapped_column(String(80))
    content_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contents.id", ondelete="CASCADE")
    )
    column_campaign_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("columns_campaigns.id", ondelete="SET NULL"),
        default=None,
    )
    selected_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )
    selected_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default_factory=utc_now
    )


class AccountStyleProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "account_style_profiles"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "scope_key",
            "version",
            name="uq_style_profile_account_scope_version",
        ),
        Index("ix_style_profiles_workspace_id", "workspace_id"),
        Index("ix_style_profiles_account_id", "account_id"),
        Index("ix_style_profiles_column_campaign_id", "column_campaign_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform_accounts.id", ondelete="CASCADE")
    )
    scope_key: Mapped[str] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[StyleProfileStatus] = mapped_column(style_profile_status_type)
    style: Mapped[dict[str, object]] = mapped_column(JSON)
    sample_content_ids: Mapped[list[str]] = mapped_column(JSON)
    diff: Mapped[dict[str, object]] = mapped_column(JSON)
    column_campaign_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("columns_campaigns.id", ondelete="SET NULL"),
        default=None,
    )
    base_profile_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("account_style_profiles.id", ondelete="SET NULL"),
        default=None,
    )
    created_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )
    confirmed_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
