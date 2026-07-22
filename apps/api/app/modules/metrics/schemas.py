from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


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
    values: dict[str, float | None]
