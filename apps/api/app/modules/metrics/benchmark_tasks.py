from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.content.account_models import BenchmarkProfile, ObjectiveProfile
from app.modules.content.models import Content
from app.modules.metrics.benchmark import (
    BenchmarkInput,
    BenchmarkRange,
    BenchmarkRangeKind,
    calculate_benchmark,
)
from app.modules.metrics.maturity import MaturityBucket
from app.modules.metrics.models import DataSnapshot, MetricOutboxEvent


BENCHMARK_ALGORITHM_VERSION = "benchmark-v1"


def process_snapshot_confirmed_event(
    session: Session,
    event_id: UUID,
) -> UUID | None:
    event = session.scalar(
        select(MetricOutboxEvent)
        .where(MetricOutboxEvent.id == event_id)
        .with_for_update()
    )
    if event is None:
        raise LookupError("metric outbox event not found")
    if event.event_type != "metrics.snapshot_confirmed":
        raise ValueError("unsupported metric outbox event")
    if event.processed_at is not None:
        return None

    snapshot = session.scalar(
        select(DataSnapshot).where(
            DataSnapshot.id == event.aggregate_id,
            DataSnapshot.workspace_id == event.workspace_id,
            DataSnapshot.confirmed.is_(True),
        )
    )
    if snapshot is None:
        raise LookupError("confirmed snapshot not found")

    content = session.scalar(
        select(Content).where(
            Content.id == snapshot.content_id,
            Content.workspace_id == snapshot.workspace_id,
            Content.account_id == snapshot.account_id,
        )
    )
    if content is None:
        raise LookupError("snapshot content not found")
    benchmark_profile = session.scalar(
        select(BenchmarkProfile).where(
            BenchmarkProfile.id == content.benchmark_profile_id,
            BenchmarkProfile.workspace_id == snapshot.workspace_id,
            BenchmarkProfile.account_id == snapshot.account_id,
        )
    )
    objective_profile = session.scalar(
        select(ObjectiveProfile).where(
            ObjectiveProfile.id == content.objective_profile_id,
            ObjectiveProfile.workspace_id == snapshot.workspace_id,
            ObjectiveProfile.account_id == snapshot.account_id,
        )
    )
    if benchmark_profile is None or objective_profile is None:
        raise LookupError("snapshot configuration not found")

    result = calculate_benchmark(
        session,
        BenchmarkInput(
            workspace_id=snapshot.workspace_id,
            platform=snapshot.platform,
            account_id=snapshot.account_id,
            content_type=snapshot.content_type,
            maturity_bucket=MaturityBucket(snapshot.maturity_bucket),
            range=BenchmarkRange(
                kind=BenchmarkRangeKind.LATEST_N,
                latest_n=benchmark_profile.sample_size,
            ),
            version=BENCHMARK_ALGORITHM_VERSION,
        ),
        weights={
            key: Decimal(str(value))
            for key, value in objective_profile.metric_weights.items()
        },
    )
    event.processed_at = datetime.now(UTC)
    session.flush()
    return result.run_id
