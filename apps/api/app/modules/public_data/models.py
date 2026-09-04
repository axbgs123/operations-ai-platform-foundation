from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
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

from app.core.database import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin
from app.modules.content.account_models import Platform, platform_type


class ProviderConfigStatus(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    DISABLED = "disabled"


class BindingStatus(StrEnum):
    ACTIVE = "active"
    ERROR = "error"
    DISABLED = "disabled"


class CollectionJobStatus(StrEnum):
    SCHEDULED = "scheduled"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


provider_config_status_enum = Enum(
    ProviderConfigStatus,
    name="public_provider_config_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)
binding_status_enum = Enum(
    BindingStatus,
    name="public_content_binding_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)
collection_job_status_enum = Enum(
    CollectionJobStatus,
    name="public_collection_job_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)


class PublicDataProviderConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "public_data_provider_configs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "provider", name="uq_public_provider_workspace"
        ),
        Index("ix_public_provider_workspace", "workspace_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    encrypted_api_key: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(40), default="tikhub")
    endpoint_region: Mapped[str] = mapped_column(String(20), default="china")
    status: Mapped[ProviderConfigStatus] = mapped_column(
        provider_config_status_enum, default=ProviderConfigStatus.UNVERIFIED
    )
    daily_request_limit: Mapped[int] = mapped_column(Integer, default=500)
    daily_usage_date: Mapped[date | None] = mapped_column(Date, default=None)
    daily_requests_used: Mapped[int] = mapped_column(Integer, default=0)
    configuration_revision: Mapped[int] = mapped_column(Integer, default=1)
    last_tested_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    safe_error_code: Mapped[str | None] = mapped_column(String(100), default=None)


class PublishedContentBinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "published_content_bindings"
    __table_args__ = (
        UniqueConstraint("content_id", name="uq_public_binding_content"),
        UniqueConstraint(
            "workspace_id",
            "platform",
            "platform_content_id",
            name="uq_public_binding_platform_content",
        ),
        Index("ix_public_binding_workspace", "workspace_id"),
        Index("ix_public_binding_account", "account_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    content_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contents.id", ondelete="CASCADE")
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform_accounts.id", ondelete="CASCADE")
    )
    platform: Mapped[Platform] = mapped_column(platform_type)
    public_url: Mapped[str] = mapped_column(String(2048))
    platform_content_id: Mapped[str] = mapped_column(String(255))
    published_at: Mapped[datetime] = mapped_column(UTCDateTime())
    locator: Mapped[dict[str, str]] = mapped_column(JSON, default_factory=dict)
    status: Mapped[BindingStatus] = mapped_column(
        binding_status_enum, default=BindingStatus.ACTIVE
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
    safe_error_code: Mapped[str | None] = mapped_column(String(100), default=None)


class PublicCollectionJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "public_collection_jobs"
    __table_args__ = (
        UniqueConstraint(
            "binding_id", "target_window", name="uq_public_collection_binding_window"
        ),
        Index(
            "ix_public_collection_due",
            "status",
            "next_attempt_at",
        ),
        Index("ix_public_collection_workspace", "workspace_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    binding_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("published_content_bindings.id", ondelete="CASCADE"),
    )
    target_window: Mapped[str] = mapped_column(String(40))
    due_at: Mapped[datetime] = mapped_column(UTCDateTime())
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[CollectionJobStatus] = mapped_column(
        collection_job_status_enum, default=CollectionJobStatus.SCHEDULED
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    claim_token: Mapped[str | None] = mapped_column(String(64), default=None)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    observation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), default=None
    )
    snapshot_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), default=None)
    safe_error_code: Mapped[str | None] = mapped_column(String(100), default=None)
    operation_version: Mapped[int] = mapped_column(Integer, default=1)


class PublicCollectionAttempt(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "public_collection_attempts"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "attempt_number", name="uq_public_collection_attempt"
        ),
        Index("ix_public_collection_attempt_workspace", "workspace_id", "started_at"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    job_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("public_collection_jobs.id", ondelete="CASCADE")
    )
    attempt_number: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(40))
    endpoint_contract: Mapped[str] = mapped_column(String(160))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    succeeded: Mapped[bool] = mapped_column(Boolean, default=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(160), default=None)
    safe_error_code: Mapped[str | None] = mapped_column(String(100), default=None)


class PublicObservation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "public_observations"
    __table_args__ = (
        Index("ix_public_observation_workspace", "workspace_id", "received_at"),
        Index("ix_public_observation_external", "platform", "platform_content_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    binding_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("published_content_bindings.id", ondelete="CASCADE"),
    )
    provider: Mapped[str] = mapped_column(String(40))
    platform: Mapped[Platform] = mapped_column(platform_type)
    platform_content_id: Mapped[str] = mapped_column(String(255))
    endpoint_contract: Mapped[str] = mapped_column(String(160))
    parser_version: Mapped[str] = mapped_column(String(80))
    provider_fetched_at: Mapped[datetime] = mapped_column(UTCDateTime())
    received_at: Mapped[datetime] = mapped_column(UTCDateTime())
    raw_response: Mapped[dict[str, object]] = mapped_column(JSON)
    raw_sha256: Mapped[str] = mapped_column(String(64))
    normalized_metrics: Mapped[dict[str, int | float | None]] = mapped_column(JSON)
