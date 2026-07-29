from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    Boolean,
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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class TextGenerationRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CoverGenerationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PROVIDER_CALLING = "provider_calling"
    PROVIDER_OUTCOME_UNKNOWN = "provider_outcome_unknown"
    DOWNLOADING = "downloading"
    VALIDATING = "validating"
    COMPOSITING = "compositing"
    RISK_SCANNING = "risk_scanning"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COMPENSATION_REQUIRED = "compensation_required"


class CoverAttemptStatus(StrEnum):
    RUNNING = "running"
    PROVIDER_CALLING = "provider_calling"
    PROVIDER_OUTCOME_UNKNOWN = "provider_outcome_unknown"
    DOWNLOADING = "downloading"
    VALIDATING = "validating"
    COMPOSITING = "compositing"
    RISK_SCANNING = "risk_scanning"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COMPENSATION_REQUIRED = "compensation_required"


text_generation_run_status_type = Enum(
    TextGenerationRunStatus,
    name="text_generation_run_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)
cover_generation_status_type = Enum(
    CoverGenerationStatus,
    name="cover_generation_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)
cover_attempt_status_type = Enum(
    CoverAttemptStatus,
    name="cover_attempt_status",
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
    operation_version: Mapped[int] = mapped_column(
        Integer,
        init=False,
        default=1,
    )
    __mapper_args__ = {"version_id_col": operation_version}


class CoverGenerationRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cover_generation_runs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "requested_by",
            "idempotency_key",
            name="uq_cover_runs_workspace_member_idempotency",
        ),
        Index(
            "ix_cover_generation_runs_workspace_status",
            "workspace_id",
            "status",
        ),
        Index("ix_cover_generation_runs_content_id", "content_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    requested_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="RESTRICT"),
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform_accounts.id", ondelete="RESTRICT"),
    )
    content_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("contents.id", ondelete="CASCADE"),
    )
    platform: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(80))
    model_id: Mapped[str] = mapped_column(String(160))
    contract_version: Mapped[str] = mapped_column(String(100))
    configuration_version: Mapped[str] = mapped_column(String(100))
    cover_mode: Mapped[str] = mapped_column(String(32))
    request_json: Mapped[dict[str, object]] = mapped_column(JSON)
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    status: Mapped[CoverGenerationStatus] = mapped_column(
        cover_generation_status_type
    )
    retry_idempotency_keys: Mapped[list[str]] = mapped_column(
        JSON, default_factory=list
    )
    model_config_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("model_configs.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    region: Mapped[str | None] = mapped_column(
        String(32), nullable=True, default=None
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    claim_token: Mapped[str | None] = mapped_column(
        String(64), default=None
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
    error_code: Mapped[str | None] = mapped_column(
        String(80), default=None
    )
    status_detail: Mapped[str | None] = mapped_column(
        String(240), default=None
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
    operation_version: Mapped[int] = mapped_column(
        Integer,
        init=False,
        default=1,
    )
    __mapper_args__ = {"version_id_col": operation_version}


class CoverArtifactAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cover_artifact_attempts"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "attempt_number",
            name="uq_cover_artifact_attempt_run_number",
        ),
        Index(
            "ix_cover_artifact_attempts_workspace_run",
            "workspace_id",
            "run_id",
        ),
        Index(
            "ix_cover_artifact_attempts_output_object",
            "output_object_key",
            unique=True,
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cover_generation_runs.id", ondelete="CASCADE"),
    )
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[CoverAttemptStatus] = mapped_column(
        cover_attempt_status_type
    )
    provider: Mapped[str] = mapped_column(String(80))
    model_id: Mapped[str] = mapped_column(String(160))
    configuration_version: Mapped[str] = mapped_column(String(100))
    contract_version: Mapped[str] = mapped_column(String(100))
    cover_mode: Mapped[str] = mapped_column(String(32))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    prompt_hash: Mapped[str] = mapped_column(String(64))
    requested_width: Mapped[int] = mapped_column(Integer)
    requested_height: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int | None] = mapped_column(Integer, default=None)
    previous_attempt_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cover_artifact_attempts.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    region: Mapped[str | None] = mapped_column(
        String(32), nullable=True, default=None
    )
    model_config_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("model_configs.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    input_assets: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, default_factory=list
    )
    provider_request_id: Mapped[str | None] = mapped_column(
        String(128), default=None
    )
    provider_started_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
    provider_completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
    billed_attempt_status: Mapped[str] = mapped_column(
        String(32), default="not_started"
    )
    output_object_key: Mapped[str | None] = mapped_column(
        String(1024), default=None
    )
    output_object_version: Mapped[str | None] = mapped_column(
        String(80), default=None
    )
    output_sha256: Mapped[str | None] = mapped_column(
        String(64), default=None
    )
    output_mime_type: Mapped[str | None] = mapped_column(
        String(120), default=None
    )
    output_width: Mapped[int | None] = mapped_column(Integer, default=None)
    output_height: Mapped[int | None] = mapped_column(Integer, default=None)
    layout_version: Mapped[str | None] = mapped_column(
        String(80), default=None
    )
    ocr_model_version: Mapped[str | None] = mapped_column(
        String(160), default=None
    )
    ocr_confidence: Mapped[float | None] = mapped_column(
        Float, default=None
    )
    risk_scan_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("risk_scans.id", ondelete="RESTRICT"),
        default=None,
    )
    risk_rule_version: Mapped[str | None] = mapped_column(
        String(160), default=None
    )
    requires_human_review: Mapped[bool] = mapped_column(
        Boolean, default=True
    )
    publish_eligible: Mapped[bool] = mapped_column(
        Boolean, default=False
    )
    disclaimer: Mapped[str] = mapped_column(
        String(160),
        default="辅助判断，不保证通过平台审核",
    )
    error_code: Mapped[str | None] = mapped_column(
        String(80), default=None
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
    operation_version: Mapped[int] = mapped_column(
        Integer,
        init=False,
        default=1,
    )
    __mapper_args__ = {"version_id_col": operation_version}
