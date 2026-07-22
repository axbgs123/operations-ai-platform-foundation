from datetime import timedelta

import pytest

from app.modules.metrics.maturity import (
    MaturityBucket,
    bucket_for_age,
    calculate_completeness,
)


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(minutes=10), MaturityBucket.HOUR_1),
        (timedelta(hours=1), MaturityBucket.HOUR_1),
        (timedelta(hours=12), MaturityBucket.HOUR_1),
        (timedelta(hours=13), MaturityBucket.HOUR_24),
        (timedelta(hours=36), MaturityBucket.HOUR_24),
        (timedelta(hours=60), MaturityBucket.HOUR_72),
        (timedelta(days=4), MaturityBucket.HOUR_72),
        (timedelta(days=6), MaturityBucket.DAY_7),
        (timedelta(days=30), MaturityBucket.DAY_7),
    ],
)
def test_custom_snapshot_age_maps_to_nearest_comparison_bucket(
    age: timedelta,
    expected: MaturityBucket,
) -> None:
    assert bucket_for_age(age) == expected


def test_snapshot_before_publication_is_rejected() -> None:
    with pytest.raises(ValueError, match="before publication"):
        bucket_for_age(timedelta(seconds=-1))


def test_recommended_nodes_are_optional_and_reported_as_completeness() -> None:
    completeness = calculate_completeness(
        [timedelta(hours=1), timedelta(hours=25), timedelta(hours=26)]
    )

    assert completeness.observed == (
        MaturityBucket.HOUR_1,
        MaturityBucket.HOUR_24,
    )
    assert completeness.missing == (
        MaturityBucket.HOUR_72,
        MaturityBucket.DAY_7,
    )
    assert completeness.ratio == 0.5


def test_no_recommended_nodes_does_not_block_current_snapshot_analysis() -> None:
    completeness = calculate_completeness([timedelta(hours=10)])

    assert completeness.observed == (MaturityBucket.HOUR_1,)
    assert completeness.ratio == 0.25
