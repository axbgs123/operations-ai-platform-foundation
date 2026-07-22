from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    JSON,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin, utc_now
from app.modules.content.account_models import Platform, platform_type
from app.modules.metrics.models import ContentType, PreciseNumeric, content_type_enum


class ViralCategory(StrEnum):
    TRAFFIC = "traffic"
    ENGAGEMENT = "engagement"
    GROWTH = "growth"
    CONVERSION = "conversion"


class ViralCandidateStatus(StrEnum):
    RECOMMENDED = "recommended"
    CONFIRMED = "confirmed"
    REVOKED = "revoked"


viral_category_type = Enum(
    ViralCategory,
    name="viral_category",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)
viral_candidate_status_type = Enum(
    ViralCandidateStatus,
    name="viral_candidate_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)


class ViralThresholdProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "viral_threshold_profiles"
    __table_args__ = (
        UniqueConstraint("account_id", "version", name="uq_viral_threshold_account_version"),
        Index("ix_viral_threshold_profiles_workspace_id", "workspace_id"),
        Index("ix_viral_threshold_profiles_account_id", "account_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform_accounts.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    rules: Mapped[list[dict[str, object]]] = mapped_column(JSON)
    objective_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("objective_profiles.id", ondelete="RESTRICT")
    )
    benchmark_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("benchmark_profiles.id", ondelete="RESTRICT")
    )
    created_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspace_members.id", ondelete="SET NULL")
    )


class ViralCandidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "viral_candidates"
    __table_args__ = (
        UniqueConstraint(
            "threshold_profile_id",
            "content_id",
            "category",
            "metric_key",
            name="uq_viral_candidate_evidence",
        ),
        Index("ix_viral_candidates_workspace_id", "workspace_id"),
        Index("ix_viral_candidates_account_id", "account_id"),
        Index("ix_viral_candidates_content_id", "content_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform_accounts.id", ondelete="CASCADE")
    )
    content_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contents.id", ondelete="CASCADE")
    )
    snapshot_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("data_snapshots.id", ondelete="RESTRICT")
    )
    platform: Mapped[Platform] = mapped_column(platform_type)
    content_type: Mapped[ContentType] = mapped_column(content_type_enum)
    maturity_bucket: Mapped[str] = mapped_column(String(8))
    category: Mapped[ViralCategory] = mapped_column(viral_category_type)
    metric_key: Mapped[str] = mapped_column(String(80))
    actual_value: Mapped[Decimal] = mapped_column(PreciseNumeric())
    percentile: Mapped[float] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(Integer)
    threshold_value: Mapped[Decimal] = mapped_column(PreciseNumeric())
    threshold_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("viral_threshold_profiles.id", ondelete="RESTRICT")
    )
    threshold_profile_version: Mapped[int] = mapped_column(Integer)
    objective_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("objective_profiles.id", ondelete="RESTRICT")
    )
    benchmark_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("benchmark_profiles.id", ondelete="RESTRICT")
    )
    evidence: Mapped[dict[str, object]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[ViralCandidateStatus] = mapped_column(
        viral_candidate_status_type,
        default=ViralCandidateStatus.RECOMMENDED,
    )


class ViralLibraryItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "viral_library_items"
    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_viral_library_candidate"),
        Index("ix_viral_library_items_workspace_id", "workspace_id"),
        Index("ix_viral_library_items_account_id", "account_id"),
        Index("ix_viral_library_items_content_id", "content_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform_accounts.id", ondelete="CASCADE")
    )
    candidate_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("viral_candidates.id", ondelete="RESTRICT")
    )
    content_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contents.id", ondelete="RESTRICT")
    )
    category: Mapped[ViralCategory] = mapped_column(viral_category_type)
    strategy_tags: Mapped[list[str]] = mapped_column(JSON)
    applicable_scenarios: Mapped[list[str]] = mapped_column(JSON)
    structure_summary: Mapped[str] = mapped_column(Text)
    confirmed_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspace_members.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default_factory=utc_now)
    revoked_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    revocation_reason: Mapped[str | None] = mapped_column(String(500), default=None)
