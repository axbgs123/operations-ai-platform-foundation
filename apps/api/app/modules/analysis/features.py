from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MetricEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=80)


class SnapshotEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    collected_at: datetime
    maturity_bucket: Literal["1h", "24h", "72h", "7d"]
    metrics: list[MetricEvidenceInput]


class ContentEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str
    body: str
    cover_asset_ids: list[UUID]
    cover_asset_metadata: list["CoverAssetEvidenceInput"] = Field(default_factory=list)


class CoverAssetEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    object_key: str
    file_name: str
    mime_type: str
    size: int = Field(ge=0)


class ComparableContentEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_id: UUID
    snapshot_id: UUID
    title: str
    performance_band: Literal["high", "low"]
    metric_key: str
    metric_value: str
    similarity_basis: str


class BenchmarkEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    sample_count: int = Field(ge=0)
    confidence: Literal["raw_only", "low_confidence", "normal"]
    percentiles: dict[str, dict[str, str]]


class AnalysisEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["content", "cover", "metric", "benchmark", "comparison"]
    label: str
    value: str
    source_id: UUID | None = None


class AnalysisEvidenceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: ContentEvidenceInput
    snapshots: list[SnapshotEvidenceInput]
    benchmark: BenchmarkEvidenceInput
    comparable_contents: list[ComparableContentEvidenceInput]
    items: list[AnalysisEvidenceItem]
    trend_allowed: bool
    confidence_ceiling: Literal["low", "medium", "high"]

    def evidence_ids(self) -> set[str]:
        return {item.id for item in self.items}


def build_analysis_evidence(
    content: ContentEvidenceInput,
    snapshots: list[SnapshotEvidenceInput],
    benchmark: BenchmarkEvidenceInput,
    comparable_contents: list[ComparableContentEvidenceInput] | None = None,
) -> AnalysisEvidenceBundle:
    ordered_snapshots = sorted(
        snapshots,
        key=lambda snapshot: (snapshot.collected_at, str(snapshot.id)),
    )
    items = [
        AnalysisEvidenceItem(
            id="content:title",
            kind="content",
            label="发布标题",
            value=content.title,
            source_id=content.id,
        ),
        AnalysisEvidenceItem(
            id="content:body",
            kind="content",
            label="发布文案",
            value=content.body,
            source_id=content.id,
        ),
    ]
    metadata_by_id = {item.id: item for item in content.cover_asset_metadata}
    if content.cover_asset_ids:
        items.extend(
            AnalysisEvidenceItem(
                id=f"cover:{asset_id}",
                kind="cover",
                label="封面素材",
                value=(
                    f"file={metadata_by_id[asset_id].file_name};"
                    f"mime={metadata_by_id[asset_id].mime_type};"
                    f"size={metadata_by_id[asset_id].size}"
                    if asset_id in metadata_by_id
                    else "已提供封面素材；尚无视觉特征"
                ),
                source_id=asset_id,
            )
            for asset_id in sorted(content.cover_asset_ids, key=str)
        )
    else:
        items.append(
            AnalysisEvidenceItem(
                id="content:cover_missing",
                kind="cover",
                label="封面素材",
                value="未提供可分析的封面素材",
                source_id=content.id,
            )
        )
    for snapshot in ordered_snapshots:
        items.extend(
            AnalysisEvidenceItem(
                id=f"snapshot:{snapshot.id}:metric:{metric.key}",
                kind="metric",
                label=f"{snapshot.maturity_bucket} {metric.key}",
                value=metric.value,
                source_id=snapshot.id,
            )
            for metric in sorted(snapshot.metrics, key=lambda metric: metric.key)
        )
    for metric_key, percentiles in sorted(benchmark.percentiles.items()):
        items.append(
            AnalysisEvidenceItem(
                id=f"benchmark:{benchmark.id}:metric:{metric_key}",
                kind="benchmark",
                label=f"{metric_key} 动态基准",
                value=";".join(
                    f"{key}={value}" for key, value in sorted(percentiles.items())
                ),
                source_id=benchmark.id,
            )
        )
    ordered_comparisons = sorted(
        comparable_contents or [],
        key=lambda item: (
            item.performance_band,
            item.metric_key,
            Decimal(item.metric_value),
            str(item.content_id),
        ),
    )
    for comparison in ordered_comparisons:
        items.append(
            AnalysisEvidenceItem(
                id=f"comparison:{comparison.content_id}:snapshot:{comparison.snapshot_id}",
                kind="comparison",
                label=(
                    "相似高表现内容"
                    if comparison.performance_band == "high"
                    else "相似低表现内容"
                ),
                value=(
                    f"title={comparison.title};{comparison.metric_key}="
                    f"{comparison.metric_value};basis={comparison.similarity_basis}"
                ),
                source_id=comparison.content_id,
            )
        )
    confidence_ceiling: Literal["low", "medium", "high"]
    expected_metric_keys = set(benchmark.percentiles)
    has_missing_metrics = any(
        expected_metric_keys
        - {metric.key for metric in snapshot.metrics}
        for snapshot in ordered_snapshots
    )
    has_missing_cover = not content.cover_asset_ids
    if benchmark.sample_count < 5 or has_missing_metrics:
        confidence_ceiling = "low"
    elif benchmark.sample_count < 10 or has_missing_cover:
        confidence_ceiling = "medium"
    else:
        confidence_ceiling = "high"
    return AnalysisEvidenceBundle(
        content=content,
        snapshots=ordered_snapshots,
        benchmark=benchmark,
        comparable_contents=ordered_comparisons,
        items=items,
        trend_allowed=len(ordered_snapshots) >= 2,
        confidence_ceiling=confidence_ceiling,
    )
