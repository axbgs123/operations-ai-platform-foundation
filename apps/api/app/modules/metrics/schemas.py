from datetime import datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


PlatformValue = Literal["douyin", "xiaohongshu"]
ContentTypeValue = Literal["video", "image_text"]
MetricUnitValue = Literal["count", "ratio", "seconds", "number"]
MetricAggregationValue = Literal["latest", "sum", "average"]


class MetricDefinitionCreate(BaseModel):
    workspace_id: UUID
    platform: PlatformValue
    content_type: ContentTypeValue
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    label: str = Field(min_length=1, max_length=120)
    unit: MetricUnitValue
    aggregation: MetricAggregationValue = "latest"
    higher_is_better: bool = True


class MetricDefinitionRead(MetricDefinitionCreate):
    id: UUID | None = None
    is_default: bool


class MetricValuesInput(BaseModel):
    values: dict[str, Decimal | None]


SnapshotSourceValue = Literal[
    "manual",
    "tabular_import",
    "screenshot",
    "extension",
    "public_api",
]


class SnapshotMetricInput(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    raw_value: Decimal | None
    ocr_confidence: float | None = Field(default=None, ge=0, le=1)


class SnapshotCreate(BaseModel):
    collected_at: datetime
    source: SnapshotSourceValue
    metrics: list[SnapshotMetricInput] = Field(min_length=1, max_length=100)
    original_screenshot_asset_id: UUID | None = None

    @field_validator("collected_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timezone is required")
        return value

    @model_validator(mode="after")
    def reject_duplicate_metric_keys(self) -> Self:
        keys = [metric.key for metric in self.metrics]
        if len(keys) != len(set(keys)):
            raise ValueError("metric keys must be unique within a snapshot")
        return self


class SnapshotMetricRead(BaseModel):
    key: str
    raw_value: Decimal | None
    normalized_value: Decimal | None
    ocr_confidence: float | None
    eligible_for_benchmark: bool


class SnapshotCompletenessRead(BaseModel):
    observed: list[Literal["1h", "24h", "72h", "7d"]]
    missing: list[Literal["1h", "24h", "72h", "7d"]]
    ratio: float


class SnapshotRead(BaseModel):
    id: UUID
    workspace_id: UUID
    content_id: UUID
    platform: PlatformValue
    content_type: ContentTypeValue
    collected_at: datetime
    age_seconds: int
    maturity_bucket: Literal["1h", "24h", "72h", "7d"]
    source: SnapshotSourceValue
    confirmed: bool
    confirmed_at: datetime | None
    original_screenshot_asset_id: UUID | None
    metrics: list[SnapshotMetricRead]
    completeness: SnapshotCompletenessRead
