from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.type_api import TypeEngine
from sqlalchemy.types import TypeDecorator

from app.core.database import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin
from app.modules.content.account_models import Platform, platform_type


class ContentType(StrEnum):
    VIDEO = "video"
    IMAGE_TEXT = "image_text"


class MetricUnit(StrEnum):
    COUNT = "count"
    RATIO = "ratio"
    SECONDS = "seconds"
    NUMBER = "number"


class MetricAggregation(StrEnum):
    LATEST = "latest"
    SUM = "sum"
    AVERAGE = "average"


class SnapshotSource(StrEnum):
    MANUAL = "manual"
    TABULAR_IMPORT = "tabular_import"
    SCREENSHOT = "screenshot"
    EXTENSION = "extension"


content_type_enum = Enum(
    ContentType,
    name="metric_content_type",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)
metric_unit_enum = Enum(
    MetricUnit,
    name="metric_unit",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)
metric_aggregation_enum = Enum(
    MetricAggregation,
    name="metric_aggregation",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)
snapshot_source_enum = Enum(
    SnapshotSource,
    name="snapshot_source",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)


class PreciseNumeric(TypeDecorator[Decimal]):
    """Keep Decimal semantics in SQLite tests and PostgreSQL production."""

    impl = Numeric
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine:
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(80))
        return dialect.type_descriptor(Numeric(24, 6))

    def process_bind_param(
        self,
        value: Decimal | None,
        dialect: Dialect,
    ) -> Decimal | str | None:
        if value is None:
            return None
        if dialect.name == "sqlite":
            return str(value)
        return value

    def process_result_value(
        self,
        value: Decimal | str | None,
        dialect: Dialect,
    ) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))


class MetricDefinition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "metric_definitions"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "platform",
            "content_type",
            "key",
            name="uq_metric_definition_scope_key",
        ),
        Index("ix_metric_definitions_workspace_id", "workspace_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    platform: Mapped[Platform] = mapped_column(platform_type)
    content_type: Mapped[ContentType] = mapped_column(content_type_enum)
    key: Mapped[str] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(String(120))
    unit: Mapped[MetricUnit] = mapped_column(metric_unit_enum)
    aggregation: Mapped[MetricAggregation] = mapped_column(metric_aggregation_enum)
    higher_is_better: Mapped[bool] = mapped_column(Boolean)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class DataSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "data_snapshots"
    __table_args__ = (
        Index("ix_data_snapshots_workspace_id", "workspace_id"),
        Index("ix_data_snapshots_content_id", "content_id"),
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
    content_type: Mapped[ContentType] = mapped_column(content_type_enum)
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime())
    age_seconds: Mapped[int] = mapped_column(Integer)
    maturity_bucket: Mapped[str] = mapped_column(String(8))
    source: Mapped[SnapshotSource] = mapped_column(snapshot_source_enum)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    confirmed_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )
    original_screenshot_asset_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("content_assets.id", ondelete="SET NULL"),
        default=None,
    )


class SnapshotMetricValue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "snapshot_metric_values"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "metric_key", name="uq_snapshot_metric_key"),
        Index("ix_snapshot_metric_values_workspace_id", "workspace_id"),
        Index("ix_snapshot_metric_values_snapshot_id", "snapshot_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    snapshot_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("data_snapshots.id", ondelete="CASCADE")
    )
    metric_key: Mapped[str] = mapped_column(String(80))
    raw_value: Mapped[Decimal | None] = mapped_column(PreciseNumeric(), default=None)
    normalized_value: Mapped[Decimal | None] = mapped_column(
        PreciseNumeric(), default=None
    )
    ocr_confidence: Mapped[float | None] = mapped_column(Float, default=None)
    eligible_for_benchmark: Mapped[bool] = mapped_column(Boolean, default=False)
    metric_definition_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("metric_definitions.id", ondelete="RESTRICT"),
        default=None,
    )


class MetricOutboxEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "metric_outbox_events"
    __table_args__ = (
        Index("ix_metric_outbox_events_workspace_id", "workspace_id"),
        Index("ix_metric_outbox_events_processed_at", "processed_at"),
        UniqueConstraint("idempotency_key", name="uq_metric_outbox_idempotency_key"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    aggregate_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict[str, str]] = mapped_column(JSON)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)


class BenchmarkRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "benchmark_runs"
    __table_args__ = (
        Index("ix_benchmark_runs_workspace_id", "workspace_id"),
        Index("ix_benchmark_runs_account_id", "account_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform_accounts.id", ondelete="CASCADE")
    )
    platform: Mapped[Platform] = mapped_column(platform_type)
    content_type: Mapped[ContentType] = mapped_column(content_type_enum)
    maturity_bucket: Mapped[str] = mapped_column(String(8))
    range_settings: Mapped[dict[str, object]] = mapped_column(JSON)
    sample_snapshot_ids: Mapped[list[str]] = mapped_column(JSON)
    sample_count: Mapped[int] = mapped_column(Integer)
    percentile_values: Mapped[dict[str, object]] = mapped_column(JSON)
    weights: Mapped[dict[str, str]] = mapped_column(JSON)
    confidence: Mapped[str] = mapped_column(String(32))
    algorithm_version: Mapped[str] = mapped_column(String(80))
