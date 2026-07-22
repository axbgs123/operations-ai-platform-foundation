from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.content.account_models import Platform
from app.modules.metrics.benchmark import (
    BenchmarkInput,
    BenchmarkRange,
    BenchmarkRangeKind,
    confidence_band,
    historical_percentile,
    percentile,
)
from app.modules.metrics.maturity import MaturityBucket
from app.modules.metrics.models import ContentType


def benchmark_input(**overrides: object) -> BenchmarkInput:
    values: dict[str, object] = {
        "workspace_id": uuid4(),
        "platform": Platform.DOUYIN,
        "account_id": uuid4(),
        "content_type": ContentType.VIDEO,
        "maturity_bucket": MaturityBucket.HOUR_24,
        "range": BenchmarkRange(kind=BenchmarkRangeKind.LATEST_N),
        "version": "benchmark-v1",
    }
    values.update(overrides)
    return BenchmarkInput.model_validate(values)


def test_fixed_array_percentiles_use_linear_interpolation() -> None:
    values = [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")]

    assert percentile(values, 0.5) == Decimal("2.5")
    assert percentile(values, 0.75) == Decimal("3.25")
    assert percentile(values, 0.9) == Decimal("3.7")


def test_historical_percentile_uses_tie_aware_midrank_and_direction() -> None:
    history = [Decimal("10"), Decimal("20"), Decimal("20"), Decimal("40")]

    assert historical_percentile(Decimal("20"), history) == Decimal("0.5")
    assert historical_percentile(
        Decimal("20"), history, higher_is_better=False
    ) == Decimal("0.5")
    assert historical_percentile(
        Decimal("10"), history, higher_is_better=False
    ) == Decimal("0.875")


@pytest.mark.parametrize(
    ("sample_count", "expected"),
    [(0, "raw_only"), (4, "raw_only"), (5, "low_confidence"), (9, "low_confidence"), (10, "normal")],
)
def test_confidence_bands(sample_count: int, expected: str) -> None:
    assert confidence_band(sample_count).value == expected


def test_latest_n_defaults_to_30_and_date_range_is_validated() -> None:
    assert benchmark_input().range.latest_n == 30

    start = datetime(2026, 7, 1, tzinfo=UTC)
    ranged = benchmark_input(
        range={
            "kind": "date_range",
            "start": start,
            "end": start + timedelta(days=7),
        }
    )
    assert ranged.range.start == start

    with pytest.raises(ValidationError):
        benchmark_input(range={"kind": "date_range", "start": start})


@pytest.mark.parametrize(
    "missing",
    [
        "workspace_id",
        "platform",
        "account_id",
        "content_type",
        "maturity_bucket",
        "range",
        "version",
    ],
)
def test_benchmark_input_rejects_every_missing_scope_field(missing: str) -> None:
    payload = benchmark_input().model_dump()
    payload.pop(missing)

    with pytest.raises(ValidationError):
        BenchmarkInput.model_validate(payload)
