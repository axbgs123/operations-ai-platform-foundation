from dataclasses import dataclass
from collections.abc import Iterable
from datetime import timedelta
from enum import StrEnum


class MaturityBucket(StrEnum):
    HOUR_1 = "1h"
    HOUR_24 = "24h"
    HOUR_72 = "72h"
    DAY_7 = "7d"


@dataclass(frozen=True, slots=True)
class SnapshotCompleteness:
    observed: tuple[MaturityBucket, ...]
    missing: tuple[MaturityBucket, ...]
    ratio: float


RECOMMENDED_NODES = (
    (MaturityBucket.HOUR_1, timedelta(hours=1)),
    (MaturityBucket.HOUR_24, timedelta(hours=24)),
    (MaturityBucket.HOUR_72, timedelta(hours=72)),
    (MaturityBucket.DAY_7, timedelta(days=7)),
)


def bucket_for_age(age: timedelta) -> MaturityBucket:
    if age < timedelta(0):
        raise ValueError("snapshot cannot be collected before publication")
    return min(RECOMMENDED_NODES, key=lambda item: abs(item[1] - age))[0]


def calculate_completeness(ages: Iterable[timedelta]) -> SnapshotCompleteness:
    observed_set = {bucket_for_age(age) for age in ages}
    ordered_buckets = tuple(bucket for bucket, _ in RECOMMENDED_NODES)
    observed = tuple(bucket for bucket in ordered_buckets if bucket in observed_set)
    missing = tuple(bucket for bucket in ordered_buckets if bucket not in observed_set)
    return SnapshotCompleteness(
        observed=observed,
        missing=missing,
        ratio=len(observed) / len(ordered_buckets),
    )
