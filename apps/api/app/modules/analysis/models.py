from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Boolean, Integer, JSON, Enum, ForeignKey, Index, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin, utc_now


class AnalysisRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


analysis_run_status_type = Enum(
    AnalysisRunStatus,
    name="analysis_run_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)


class AnalysisRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        Index("ix_analysis_runs_workspace_id", "workspace_id"),
        Index("ix_analysis_runs_content_id", "content_id"),
        Index("ix_analysis_runs_cache_key", "cache_key"),
        Index(
            "uq_analysis_runs_active_cache",
            "content_id",
            "cache_key",
            unique=True,
            postgresql_where=text(
                "status IN ('pending', 'running', 'succeeded')"
            ),
            sqlite_where=text("status IN ('pending', 'running', 'succeeded')"),
        ),
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
    benchmark_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("benchmark_runs.id", ondelete="RESTRICT")
    )
    snapshot_ids: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[AnalysisRunStatus] = mapped_column(analysis_run_status_type)
    trigger_kind: Mapped[str] = mapped_column(String(20))
    cache_key: Mapped[str] = mapped_column(String(64))
    evidence_bundle: Mapped[dict[str, object]] = mapped_column(JSON)
    model_version: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(80))
    algorithm_version: Mapped[str] = mapped_column(String(80))
    benchmark_algorithm_version: Mapped[str] = mapped_column(String(80))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default_factory=utc_now
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
    report: Mapped[dict[str, object] | None] = mapped_column(JSON, default=None)
    error_code: Mapped[str | None] = mapped_column(String(80), default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    requested_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)


class AccountAnalysisSetting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "account_analysis_settings"
    __table_args__ = (
        UniqueConstraint("account_id", name="uq_account_analysis_setting_account"),
        Index("ix_account_analysis_settings_workspace_id", "workspace_id"),
        Index("ix_account_analysis_settings_account_id", "account_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform_accounts.id", ondelete="CASCADE")
    )
    auto_analyze: Mapped[bool] = mapped_column(Boolean, default=False)


class AnalysisSuggestion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "analysis_suggestions"
    __table_args__ = (
        UniqueConstraint(
            "analysis_run_id",
            "recommendation_id",
            name="uq_analysis_suggestion_recommendation",
        ),
        Index("ix_analysis_suggestions_workspace_id", "workspace_id"),
        Index("ix_analysis_suggestions_run_id", "analysis_run_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    analysis_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="CASCADE")
    )
    recommendation_id: Mapped[str] = mapped_column(String(80))
    recommendation: Mapped[dict[str, object]] = mapped_column(JSON)
    adoption_status: Mapped[str] = mapped_column(String(20), default="saved")


class ProductEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "product_events"
    __table_args__ = (
        Index("ix_product_events_workspace_id", "workspace_id"),
        Index("ix_product_events_entity", "entity_type", "entity_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    event_name: Mapped[str] = mapped_column(String(120))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime())
    actor_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )
    properties: Mapped[dict[str, object]] = mapped_column(JSON, default_factory=dict)
