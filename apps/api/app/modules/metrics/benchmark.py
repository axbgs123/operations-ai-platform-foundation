from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.content.account_models import Platform
from app.modules.content.models import Content
from app.modules.metrics.maturity import MaturityBucket
from app.modules.metrics.models import (
    BenchmarkRun,
    ContentType,
    DataSnapshot,
    SnapshotMetricValue,
)


class BenchmarkRangeKind(StrEnum):
    LATEST_N = "latest_n"
    DATE_RANGE = "date_range"
    ALL_HISTORY = "all_history"


class BenchmarkConfidence(StrEnum):
    RAW_ONLY = "raw_only"
    LOW_CONFIDENCE = "low_confidence"
    NORMAL = "normal"


class BenchmarkRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: BenchmarkRangeKind
    latest_n: int = Field(default=30, ge=1)
    start: datetime | None = None
    end: datetime | None = None
    column_campaign_id: UUID | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> "BenchmarkRange":
        if self.kind == BenchmarkRangeKind.DATE_RANGE:
            if self.start is None or self.end is None:
                raise ValueError("date_range requires start and end")
            if self.start.tzinfo is None or self.end.tzinfo is None:
                raise ValueError("date range must be timezone-aware")
            if self.start > self.end:
                raise ValueError("date range start must not be after end")
        return self


class BenchmarkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: UUID
    platform: Platform
    account_id: UUID
    content_type: ContentType
    maturity_bucket: MaturityBucket
    range: BenchmarkRange
    version: str = Field(min_length=1, max_length=80)


@dataclass(frozen=True)
class MetricPercentiles:
    median: Decimal
    p75: Decimal
    p90: Decimal


@dataclass(frozen=True)
class BenchmarkResult:
    run_id: UUID
    sample_snapshot_ids: list[UUID]
    sample_count: int
    percentiles: dict[str, MetricPercentiles]
    confidence: BenchmarkConfidence


def percentile(values: list[Decimal], quantile: float) -> Decimal:
    """Return a reproducible linear-interpolation percentile."""
    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between 0 and 1")
    ordered = sorted(values)
    position = Decimal(str(quantile)) * Decimal(len(ordered) - 1)
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - lower_index
    return ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction


def historical_percentile(
    value: Decimal,
    history: list[Decimal],
    *,
    higher_is_better: bool = True,
) -> Decimal:
    """Return an empirical percentile using midrank for ties."""
    if not history:
        raise ValueError("historical percentile requires at least one value")
    below = sum(item < value for item in history)
    equal = sum(item == value for item in history)
    rank = (Decimal(below) + Decimal(equal) / 2) / Decimal(len(history))
    return rank if higher_is_better else Decimal(1) - rank


def confidence_band(sample_count: int) -> BenchmarkConfidence:
    if sample_count < 5:
        return BenchmarkConfidence.RAW_ONLY
    if sample_count < 10:
        return BenchmarkConfidence.LOW_CONFIDENCE
    return BenchmarkConfidence.NORMAL


def _comparable_snapshots(
    session: Session,
    benchmark_input: BenchmarkInput,
) -> list[DataSnapshot]:
    filters = [
        DataSnapshot.workspace_id == benchmark_input.workspace_id,
        DataSnapshot.platform == benchmark_input.platform,
        DataSnapshot.account_id == benchmark_input.account_id,
        DataSnapshot.content_type == benchmark_input.content_type,
        DataSnapshot.maturity_bucket == benchmark_input.maturity_bucket.value,
        DataSnapshot.confirmed.is_(True),
        Content.workspace_id == benchmark_input.workspace_id,
        Content.account_id == benchmark_input.account_id,
        Content.platform == benchmark_input.platform,
        Content.content_type == benchmark_input.content_type,
        Content.deleted_at.is_(None),
    ]
    range_input = benchmark_input.range
    if range_input.column_campaign_id is not None:
        filters.append(Content.column_campaign_id == range_input.column_campaign_id)
    if range_input.kind == BenchmarkRangeKind.DATE_RANGE:
        assert range_input.start is not None
        assert range_input.end is not None
        filters.extend(
            [
                Content.published_at >= range_input.start,
                Content.published_at <= range_input.end,
            ]
        )

    candidates = list(
        session.scalars(
            select(DataSnapshot)
            .join(Content, Content.id == DataSnapshot.content_id)
            .where(*filters)
            .order_by(
                Content.published_at.desc(),
                DataSnapshot.collected_at.desc(),
                DataSnapshot.created_at.desc(),
                DataSnapshot.id.desc(),
            )
        )
    )

    latest_per_content: list[DataSnapshot] = []
    seen_content_ids: set[UUID] = set()
    for snapshot in candidates:
        if snapshot.content_id not in seen_content_ids:
            latest_per_content.append(snapshot)
            seen_content_ids.add(snapshot.content_id)
    if range_input.kind == BenchmarkRangeKind.LATEST_N:
        return latest_per_content[: range_input.latest_n]
    return latest_per_content


def _metric_values(
    session: Session,
    workspace_id: UUID,
    snapshot_ids: list[UUID],
) -> dict[str, list[Decimal]]:
    if not snapshot_ids:
        return {}
    rows = session.execute(
        select(
            SnapshotMetricValue.snapshot_id,
            SnapshotMetricValue.metric_key,
            SnapshotMetricValue.normalized_value,
        ).where(
            SnapshotMetricValue.workspace_id == workspace_id,
            SnapshotMetricValue.snapshot_id.in_(snapshot_ids),
            SnapshotMetricValue.eligible_for_benchmark.is_(True),
            SnapshotMetricValue.normalized_value.is_not(None),
        )
    )
    by_metric: dict[str, list[Decimal]] = {}
    for _, metric_key, normalized_value in rows:
        if normalized_value is not None:
            by_metric.setdefault(metric_key, []).append(normalized_value)
    return by_metric


def _range_settings(range_input: BenchmarkRange) -> dict[str, object]:
    return {
        key: value
        for key, value in range_input.model_dump(mode="json").items()
        if value is not None
    }


def calculate_benchmark(
    session: Session,
    benchmark_input: BenchmarkInput,
    *,
    weights: dict[str, Decimal] | None = None,
) -> BenchmarkResult:
    snapshots = _comparable_snapshots(session, benchmark_input)
    snapshot_ids = [snapshot.id for snapshot in snapshots]
    values = _metric_values(session, benchmark_input.workspace_id, snapshot_ids)
    percentiles = {
        metric_key: MetricPercentiles(
            median=percentile(metric_values, 0.5),
            p75=percentile(metric_values, 0.75),
            p90=percentile(metric_values, 0.9),
        )
        for metric_key, metric_values in sorted(values.items())
    }
    confidence = confidence_band(len(snapshot_ids))
    serialized_percentiles: dict[str, object] = {
        key: {
            "median": str(value.median),
            "p75": str(value.p75),
            "p90": str(value.p90),
        }
        for key, value in percentiles.items()
    }
    serialized_weights = {
        key: str(value) for key, value in sorted((weights or {}).items())
    }
    run = BenchmarkRun(
        workspace_id=benchmark_input.workspace_id,
        account_id=benchmark_input.account_id,
        platform=benchmark_input.platform,
        content_type=benchmark_input.content_type,
        maturity_bucket=benchmark_input.maturity_bucket.value,
        range_settings=_range_settings(benchmark_input.range),
        sample_snapshot_ids=[str(snapshot_id) for snapshot_id in snapshot_ids],
        sample_count=len(snapshot_ids),
        percentile_values=serialized_percentiles,
        weights=serialized_weights,
        confidence=confidence.value,
        algorithm_version=benchmark_input.version,
    )
    session.add(run)
    session.flush()
    return BenchmarkResult(
        run_id=run.id,
        sample_snapshot_ids=snapshot_ids,
        sample_count=len(snapshot_ids),
        percentiles=percentiles,
        confidence=confidence,
    )
