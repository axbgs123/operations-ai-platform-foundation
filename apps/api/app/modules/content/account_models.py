from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, Enum, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class Platform(StrEnum):
    DOUYIN = "douyin"
    XIAOHONGSHU = "xiaohongshu"


class ColumnCampaignKind(StrEnum):
    COLUMN = "column"
    CAMPAIGN = "campaign"


platform_type = Enum(
    Platform,
    name="content_platform",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)
column_campaign_kind_type = Enum(
    ColumnCampaignKind,
    name="column_campaign_kind",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)


class PlatformAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "platform_accounts"
    __table_args__ = (Index("ix_platform_accounts_workspace_id", "workspace_id"),)

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    platform: Mapped[Platform] = mapped_column(platform_type)
    name: Mapped[str] = mapped_column(String(120))


class ObjectiveProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "objective_profiles"
    __table_args__ = (
        UniqueConstraint("account_id", "version", name="uq_objective_account_version"),
        Index("ix_objective_profiles_workspace_id", "workspace_id"),
        Index("ix_objective_profiles_account_id", "account_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform_accounts.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    objectives: Mapped[list[str]] = mapped_column(JSON)
    metric_weights: Mapped[dict[str, float]] = mapped_column(JSON)
    is_account_default: Mapped[bool] = mapped_column(Boolean, default=True)


class BenchmarkProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "benchmark_profiles"
    __table_args__ = (
        UniqueConstraint("account_id", "version", name="uq_benchmark_account_version"),
        Index("ix_benchmark_profiles_workspace_id", "workspace_id"),
        Index("ix_benchmark_profiles_account_id", "account_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform_accounts.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    sample_size: Mapped[int] = mapped_column(Integer)
    is_account_default: Mapped[bool] = mapped_column(Boolean, default=True)


class ColumnCampaign(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "columns_campaigns"
    __table_args__ = (
        Index("ix_columns_campaigns_workspace_id", "workspace_id"),
        Index("ix_columns_campaigns_account_id", "account_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform_accounts.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[ColumnCampaignKind] = mapped_column(column_campaign_kind_type)
    starts_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    objective_profile_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("objective_profiles.id", ondelete="SET NULL"), default=None
    )
    benchmark_profile_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("benchmark_profiles.id", ondelete="SET NULL"), default=None
    )
