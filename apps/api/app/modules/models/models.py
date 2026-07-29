from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    JSON,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.database import UTCDateTime, utc_now


class ModelConfigStatus(StrEnum):
    VERIFIED = "verified"
    EXPERIMENTAL = "experimental"
    COMMUNITY = "community"
    INCOMPATIBLE = "incompatible"


model_config_status_type = Enum(
    ModelConfigStatus,
    name="model_config_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)


class ModelConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "model_configs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "provider",
            "model_id",
            name="uq_model_config_workspace_provider_model",
        ),
        CheckConstraint(
            "provider <> 'qianwen' OR "
            "(region IS NOT NULL AND provider_workspace_id IS NOT NULL)",
            name="ck_model_configs_qianwen_endpoint_fields",
        ),
        Index("ix_model_configs_workspace_id", "workspace_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    provider: Mapped[str] = mapped_column(String(80))
    model_id: Mapped[str] = mapped_column(String(160))
    capabilities: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[ModelConfigStatus] = mapped_column(model_config_status_type)
    encrypted_api_key: Mapped[str] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        default=None,
    )
    provider_workspace_id: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        default=None,
    )
    encryption_key_version: Mapped[str] = mapped_column(String(20), default="v1")
    credential_updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default_factory=utc_now,
    )
    configuration_revision: Mapped[int] = mapped_column(default=1)


class ModelUsageReservationStatus(StrEnum):
    RESERVED = "reserved"
    SETTLED = "settled"
    RELEASED = "released"
    UNKNOWN = "unknown"
    EXPIRED = "expired"


model_usage_reservation_status_type = Enum(
    ModelUsageReservationStatus,
    name="model_usage_reservation_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)


class ModelUsageAttemptStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED_UNBILLED = "failed_unbilled"
    FAILED_POSSIBLY_BILLED = "failed_possibly_billed"
    PROVIDER_OUTCOME_UNKNOWN = "provider_outcome_unknown"
    CANCELLED_UNKNOWN = "cancelled_unknown"


model_usage_attempt_status_type = Enum(
    ModelUsageAttemptStatus,
    name="model_usage_attempt_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)


class ModelValidationResult(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"


model_validation_result_type = Enum(
    ModelValidationResult,
    name="model_validation_result",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)


class ModelUsagePolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "model_usage_policies"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "capability",
            "version",
            name="uq_model_usage_policy_workspace_capability_version",
        ),
        Index(
            "ix_model_usage_policy_workspace_capability",
            "workspace_id",
            "capability",
            "effective_from",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    capability: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean)
    max_concurrent_calls: Mapped[int] = mapped_column(Integer)
    max_calls_per_minute: Mapped[int] = mapped_column(Integer)
    daily_request_limit: Mapped[int] = mapped_column(Integer)
    daily_input_token_limit: Mapped[int] = mapped_column(BigInteger)
    daily_output_token_limit: Mapped[int] = mapped_column(BigInteger)
    daily_embedding_token_limit: Mapped[int] = mapped_column(BigInteger)
    daily_ocr_image_limit: Mapped[int] = mapped_column(Integer)
    daily_generated_image_limit: Mapped[int] = mapped_column(Integer)
    daily_cost_limit_microunits: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(8))
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime())
    version: Mapped[int] = mapped_column(Integer)
    updated_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))


class ModelUsageReservation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "model_usage_reservations"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "task_id",
            "attempt_id",
            "provider_attempt_number",
            name="uq_model_usage_reservation_attempt",
        ),
        Index(
            "ix_model_usage_reservation_workspace_created",
            "workspace_id",
            "created_at",
        ),
        Index(
            "ix_model_usage_reservation_workspace_capability_status",
            "workspace_id",
            "capability",
            "status",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    model_config_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("model_configs.id", ondelete="RESTRICT"),
    )
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    task_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    attempt_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    provider_attempt_number: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(80))
    model_id: Mapped[str] = mapped_column(String(160))
    region: Mapped[str] = mapped_column(String(32))
    capability: Mapped[str] = mapped_column(String(32))
    operation: Mapped[str] = mapped_column(String(48))
    contract_version: Mapped[str] = mapped_column(String(120))
    configuration_version: Mapped[str] = mapped_column(String(100))
    policy_version: Mapped[int] = mapped_column(Integer)
    pricing_version: Mapped[str] = mapped_column(String(80))
    estimated_usage: Mapped[dict[str, int]] = mapped_column(JSON)
    reserved_cost_microunits: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[ModelUsageReservationStatus] = mapped_column(
        model_usage_reservation_status_type
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    operation_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default_factory=utc_now,
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
        default=None,
    )


class ModelUsageAttempt(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "model_usage_attempts"
    __table_args__ = (
        UniqueConstraint(
            "reservation_id",
            name="uq_model_usage_attempt_reservation",
        ),
        Index(
            "ix_model_usage_attempt_workspace_created",
            "workspace_id",
            "created_at",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    reservation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("model_usage_reservations.id", ondelete="RESTRICT"),
    )
    task_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    attempt_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    provider_attempt_number: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(80))
    model_id: Mapped[str] = mapped_column(String(160))
    region: Mapped[str] = mapped_column(String(32))
    capability: Mapped[str] = mapped_column(String(32))
    operation: Mapped[str] = mapped_column(String(48))
    contract_version: Mapped[str] = mapped_column(String(120))
    configuration_version: Mapped[str] = mapped_column(String(100))
    pricing_version: Mapped[str] = mapped_column(String(80))
    usage_basis: Mapped[str] = mapped_column(String(16))
    status: Mapped[ModelUsageAttemptStatus] = mapped_column(
        model_usage_attempt_status_type
    )
    input_tokens: Mapped[int] = mapped_column(BigInteger)
    output_tokens: Mapped[int] = mapped_column(BigInteger)
    total_tokens: Mapped[int] = mapped_column(BigInteger)
    image_inputs: Mapped[int] = mapped_column(Integer)
    image_outputs: Mapped[int] = mapped_column(Integer)
    embedding_inputs: Mapped[int] = mapped_column(BigInteger)
    estimated_cost_microunits: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(8))
    latency_ms: Mapped[int] = mapped_column(Integer)
    settled_cost_microunits: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        default=None,
    )
    provider_request_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        default=None,
    )
    stable_error_code: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default_factory=utc_now,
    )


class ModelContractValidationRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "model_contract_validation_runs"
    __table_args__ = (
        Index(
            "ix_model_validation_workspace_created",
            "workspace_id",
            "created_at",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    model_config_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("model_configs.id", ondelete="RESTRICT"),
    )
    region: Mapped[str] = mapped_column(String(32))
    capability: Mapped[str] = mapped_column(String(32))
    model_id: Mapped[str] = mapped_column(String(160))
    contract_version: Mapped[str] = mapped_column(String(120))
    configuration_version: Mapped[str] = mapped_column(String(100))
    validation_suite_version: Mapped[str] = mapped_column(String(80))
    max_calls: Mapped[int] = mapped_column(Integer)
    max_input_tokens: Mapped[int] = mapped_column(BigInteger)
    max_output_tokens: Mapped[int] = mapped_column(BigInteger)
    max_images: Mapped[int] = mapped_column(Integer)
    max_cost_microunits: Mapped[int] = mapped_column(BigInteger)
    result: Mapped[ModelValidationResult] = mapped_column(
        model_validation_result_type
    )
    evidence: Mapped[dict[str, int | str | bool | None]] = mapped_column(JSON)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    safe_error_code: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        default=None,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default_factory=utc_now,
    )
