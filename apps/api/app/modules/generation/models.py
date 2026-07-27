from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import JSON, Enum, Float, ForeignKey, Index, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class TextGenerationRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


text_generation_run_status_type = Enum(
    TextGenerationRunStatus,
    name="text_generation_run_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)


class TextGenerationRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "text_generation_runs"
    __table_args__ = (
        Index("ix_text_generation_runs_workspace_id", "workspace_id"),
        Index("ix_text_generation_runs_cache_key", "cache_key"),
        Index(
            "uq_text_generation_runs_active_cache",
            "workspace_id",
            "cache_key",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running', 'succeeded')"),
            sqlite_where=text("status IN ('queued', 'running', 'succeeded')"),
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform_accounts.id", ondelete="CASCADE"),
    )
    model_config_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("model_configs.id", ondelete="RESTRICT"),
    )
    cache_key: Mapped[str] = mapped_column(String(64))
    context: Mapped[dict[str, object]] = mapped_column(JSON)
    status: Mapped[TextGenerationRunStatus] = mapped_column(
        text_generation_run_status_type
    )
    original_result: Mapped[dict[str, object] | None] = mapped_column(
        JSON,
        default=None,
    )
    final_title: Mapped[str | None] = mapped_column(Text, default=None)
    final_copy: Mapped[str | None] = mapped_column(Text, default=None)
    adoption_status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
    )
    modification_magnitude: Mapped[float] = mapped_column(Float, default=0.0)
    modification_algorithm_version: Mapped[str] = mapped_column(
        String(80),
        default="normalized-levenshtein-v1",
    )
    retry_of_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("text_generation_runs.id", ondelete="SET NULL"),
        default=None,
    )
    requested_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )
    error_code: Mapped[str | None] = mapped_column(
        String(80),
        default=None,
    )
    status_detail: Mapped[str | None] = mapped_column(Text, default=None)
    completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        default=None,
    )
