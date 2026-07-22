from enum import StrEnum
from uuid import UUID

from sqlalchemy import Boolean, Enum, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UUIDPrimaryKeyMixin
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
