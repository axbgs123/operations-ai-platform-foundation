from datetime import datetime
from typing import Literal, cast
import unicodedata
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext


DEFAULT_TIMEZONE = "Asia/Shanghai"
EDIT_ALGORITHM_VERSION = "normalized-levenshtein-v1"
COMPLETENESS_VERSION = "profile-completeness-v1"
FIRST_ANALYSIS_VERSION = "first-analysis-duration-v1"
EFFECTIVE_LOOP_VERSION = "effective-weekly-loop-v1"
RETENTION_VERSION = "weekly-loop-retention-v1"


class AnalyticsEventFact(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: UUID
    event_name: str
    workspace_id: UUID
    platform: str
    occurred_at: datetime
    analytics_eligible: bool


class EditMagnitude(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: float
    body: float
    total: float
    algorithm_version: str = EDIT_ALGORITHM_VERSION


def _normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _levenshtein(left: str, right: str) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_character in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_character in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1]
                    + (left_character != right_character),
                )
            )
        previous = current
    return previous[-1]


def _distance(left: str, right: str) -> tuple[float, int]:
    normalized_left = _normalize_text(left)
    normalized_right = _normalize_text(right)
    denominator = max(len(normalized_left), len(normalized_right))
    if denominator == 0:
        return 0.0, 0
    return _levenshtein(normalized_left, normalized_right) / denominator, denominator


def calculate_normalized_edit_magnitude(
    *,
    original_title: str,
    original_body: str,
    final_title: str,
    final_body: str,
) -> EditMagnitude:
    title, title_weight = _distance(original_title, final_title)
    body, body_weight = _distance(original_body, final_body)
    denominator = title_weight + body_weight
    total = (
        0.0
        if denominator == 0
        else (title * title_weight + body * body_weight) / denominator
    )
    return EditMagnitude(
        title=round(title, 6),
        body=round(body, 6),
        total=round(total, 6),
    )


class DurationMetric(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["AVAILABLE", "INSUFFICIENT_SAMPLE"]
    total_seconds: int | None
    queue_seconds: int | None
    processing_seconds: int | None
    queue_and_processing_seconds: int | None
    user_wait_seconds: int | None
    metric_version: str = FIRST_ANALYSIS_VERSION


def calculate_first_analysis_duration(
    *,
    workspace_entered_at: datetime | None,
    events: list[AnalyticsEventFact],
) -> DurationMetric:
    if workspace_entered_at is None:
        return DurationMetric(
            status="INSUFFICIENT_SAMPLE",
            total_seconds=None,
            queue_seconds=None,
            processing_seconds=None,
            queue_and_processing_seconds=None,
            user_wait_seconds=None,
        )
    eligible = sorted(
        (event for event in events if event.analytics_eligible),
        key=lambda event: (event.occurred_at, event.event_id),
    )
    started = next(
        (
            event
            for event in eligible
            if event.event_name == "analysis.started"
        ),
        None,
    )
    if started is None:
        return DurationMetric(
            status="INSUFFICIENT_SAMPLE",
            total_seconds=None,
            queue_seconds=None,
            processing_seconds=None,
            queue_and_processing_seconds=None,
            user_wait_seconds=None,
        )
    completed = next(
        (
            event
            for event in eligible
            if event.event_name == "analysis.completed"
            and event.occurred_at >= started.occurred_at
        ),
        None,
    )
    processing_started = next(
        (
            event
            for event in eligible
            if event.event_name == "analysis.processing_started"
            and event.occurred_at >= started.occurred_at
            and (
                completed is None
                or event.occurred_at <= completed.occurred_at
            )
        ),
        None,
    )
    viewed = next(
        (
            event
            for event in eligible
            if completed is not None
            and event.event_name == "analysis.viewed"
            and event.occurred_at >= completed.occurred_at
        ),
        None,
    )
    if completed is None or viewed is None:
        return DurationMetric(
            status="INSUFFICIENT_SAMPLE",
            total_seconds=None,
            queue_seconds=None,
            processing_seconds=None,
            queue_and_processing_seconds=None,
            user_wait_seconds=None,
        )
    return DurationMetric(
        status="AVAILABLE",
        total_seconds=max(
            0,
            int((viewed.occurred_at - workspace_entered_at).total_seconds()),
        ),
        queue_seconds=max(
            0,
            int(
                (
                    (processing_started or started).occurred_at
                    - started.occurred_at
                ).total_seconds()
            ),
        ),
        processing_seconds=max(
            0,
            int(
                (
                    completed.occurred_at
                    - (processing_started or started).occurred_at
                ).total_seconds()
            ),
        ),
        queue_and_processing_seconds=max(
            0,
            int((completed.occurred_at - started.occurred_at).total_seconds()),
        ),
        user_wait_seconds=max(
            0,
            int((viewed.occurred_at - completed.occurred_at).total_seconds()),
        ),
    )


class CompletenessInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    platform: Literal["douyin", "xiaohongshu"]
    has_objective: bool
    has_metric_weights: bool
    has_benchmark: bool
    has_column_campaign: bool
    has_confirmed_style: bool
    has_confirmed_facts: bool
    has_title: bool
    has_body: bool
    has_cover: bool
    has_confirmed_snapshot: bool
    has_active_risk_knowledge: bool
    has_active_model: bool
    is_demo: bool = False


class CompletenessItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    weight: int
    applicable: bool
    complete: bool


class CompletenessResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    score: float
    denominator: int
    items: tuple[CompletenessItem, ...]
    missing_items: tuple[str, ...]
    completeness_version: str = COMPLETENESS_VERSION
    analytics_eligible: bool


_COMPLETENESS_WEIGHTS = {
    "objective": 10,
    "metric_weights": 10,
    "benchmark": 10,
    "column_campaign": 5,
    "confirmed_style": 10,
    "confirmed_facts": 10,
    "title": 5,
    "body": 5,
    "cover": 5,
    "confirmed_snapshot": 15,
    "active_risk_knowledge": 10,
    "active_model": 5,
}


def calculate_completeness(data: CompletenessInput) -> CompletenessResult:
    values = {
        key: bool(getattr(data, f"has_{key}"))
        for key in _COMPLETENESS_WEIGHTS
    }
    items: list[CompletenessItem] = []
    for key, configured_weight in _COMPLETENESS_WEIGHTS.items():
        applicable = not (
            key == "column_campaign" and data.platform == "xiaohongshu"
        )
        items.append(
            CompletenessItem(
                key=key,
                weight=configured_weight if applicable else 0,
                applicable=applicable,
                complete=values[key] if applicable else False,
            )
        )
    denominator = sum(item.weight for item in items if item.applicable)
    completed = sum(
        item.weight for item in items if item.applicable and item.complete
    )
    return CompletenessResult(
        score=round(completed / denominator, 6) if denominator else 0,
        denominator=denominator,
        items=tuple(items),
        missing_items=tuple(
            item.key
            for item in items
            if item.applicable and not item.complete
        ),
        analytics_eligible=not data.is_demo,
    )


class LoopEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace_id: UUID
    platform: Literal["douyin", "xiaohongshu"]
    published_content_id: UUID | None
    published_at: datetime | None
    confirmed_snapshot_id: UUID | None
    snapshot_confirmed_at: datetime | None
    snapshot_analytics_eligible: bool
    events: list[AnalyticsEventFact]


class EffectiveWeeklyLoop(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace_id: UUID
    platform: str
    iso_week: str
    completed_at: datetime
    evidence_ids: dict[str, str]
    metric_version: str = EFFECTIVE_LOOP_VERSION


def _iso_week(value: datetime, timezone_name: str) -> str:
    local = value.astimezone(ZoneInfo(timezone_name))
    year, week, _ = local.isocalendar()
    return f"{year}-W{week:02d}"


def derive_effective_weekly_loops(
    evidence_sets: list[LoopEvidence],
    *,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> list[EffectiveWeeklyLoop]:
    candidates: list[EffectiveWeeklyLoop] = []
    for evidence in evidence_sets:
        if (
            evidence.published_content_id is None
            or evidence.published_at is None
            or evidence.confirmed_snapshot_id is None
            or evidence.snapshot_confirmed_at is None
            or not evidence.snapshot_analytics_eligible
            or evidence.snapshot_confirmed_at < evidence.published_at
        ):
            continue
        scoped = sorted(
            (
                event
                for event in evidence.events
                if event.analytics_eligible
                and event.workspace_id == evidence.workspace_id
                and event.platform == evidence.platform
            ),
            key=lambda event: (event.occurred_at, event.event_id),
        )
        cutoff = evidence.snapshot_confirmed_at
        for outcome in (
            event
            for event in scoped
            if event.event_name in {"suggestion.saved", "draft.created"}
        ):
            viewed = next(
                (
                    event
                    for event in reversed(scoped)
                    if event.event_name == "analysis.viewed"
                    and cutoff <= event.occurred_at <= outcome.occurred_at
                ),
                None,
            )
            if viewed is None:
                continue
            candidates.append(
                EffectiveWeeklyLoop(
                    workspace_id=evidence.workspace_id,
                    platform=evidence.platform,
                    iso_week=_iso_week(outcome.occurred_at, timezone_name),
                    completed_at=outcome.occurred_at,
                    evidence_ids={
                        "content_id": str(evidence.published_content_id),
                        "snapshot_id": str(evidence.confirmed_snapshot_id),
                        "analysis_view_event_id": str(viewed.event_id),
                        "outcome_event_id": str(outcome.event_id),
                    },
                )
            )
            cutoff = outcome.occurred_at
    candidates.sort(
        key=lambda loop: (
            loop.iso_week,
            str(loop.workspace_id),
            loop.completed_at,
            loop.platform,
        )
    )
    deduplicated: dict[tuple[UUID, str], EffectiveWeeklyLoop] = {}
    for loop in candidates:
        deduplicated.setdefault((loop.workspace_id, loop.iso_week), loop)
    return list(deduplicated.values())


class WeeklyRetention(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["AVAILABLE", "INSUFFICIENT_SAMPLE"]
    baseline_week: str
    return_week: str
    denominator: int
    returned_workspaces: int
    rate: float | None
    metric_version: str = RETENTION_VERSION


def calculate_weekly_retention(
    *,
    baseline_week: str,
    return_week: str,
    loops: list[EffectiveWeeklyLoop],
) -> WeeklyRetention:
    baseline = {
        loop.workspace_id for loop in loops if loop.iso_week == baseline_week
    }
    returned = {
        loop.workspace_id for loop in loops if loop.iso_week == return_week
    } & baseline
    if not baseline:
        return WeeklyRetention(
            status="INSUFFICIENT_SAMPLE",
            baseline_week=baseline_week,
            return_week=return_week,
            denominator=0,
            returned_workspaces=0,
            rate=None,
        )
    return WeeklyRetention(
        status="AVAILABLE",
        baseline_week=baseline_week,
        return_week=return_week,
        denominator=len(baseline),
        returned_workspaces=len(returned),
        rate=round(len(returned) / len(baseline), 6),
    )


class CollectionDuration(BaseModel):
    model_config = ConfigDict(frozen=True)

    platform: str
    source: str
    sample_count: int
    average_seconds: float | None
    metric_version: str = "collection-duration-v1"


class ProductMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    first_analysis: DurationMetric
    collection_durations: tuple[CollectionDuration, ...]
    analysis_feedback_latest: dict[str, int]
    suggestion_saved: int
    suggestion_adopted: int
    suggestion_save_denominator: int
    suggestion_adoption_rate: float | None
    generation_statuses: dict[str, int]
    metric_version: str = "workspace-product-metrics-v1"


class AnalyticsService:
    def __init__(self, session: Session, context: WorkspaceContext) -> None:
        self._session = session
        self._context = context

    def _account(self, account_id: UUID):
        from app.modules.content.account_models import PlatformAccount

        account = self._session.scalar(
            select(PlatformAccount).where(
                PlatformAccount.id == account_id,
                PlatformAccount.workspace_id == self._context.workspace_id,
            )
        )
        if account is None:
            raise LookupError("account not found")
        return account

    def _facts(self) -> list[AnalyticsEventFact]:
        from app.modules.analysis.models import ProductEvent

        return [
            AnalyticsEventFact(
                event_id=event.id,
                event_name=event.event_name,
                workspace_id=event.workspace_id,
                platform=event.platform.value if event.platform else "",
                occurred_at=event.server_occurred_at,
                analytics_eligible=event.analytics_eligible,
            )
            for event in self._session.scalars(
                select(ProductEvent)
                .where(
                    ProductEvent.workspace_id == self._context.workspace_id
                )
                .order_by(
                    ProductEvent.server_occurred_at,
                    ProductEvent.id,
                )
            )
        ]

    def completeness(
        self,
        account_id: UUID,
        *,
        content_id: UUID | None = None,
    ) -> CompletenessResult:
        from app.modules.content.account_models import (
            BenchmarkProfile,
            ColumnCampaign,
            ObjectiveProfile,
        )
        from app.modules.content.models import AssetCategory, Content, ContentAsset
        from app.modules.metrics.models import DataSnapshot
        from app.modules.models.models import ModelConfig, ModelConfigStatus
        from app.modules.risk_rag.models import (
            RiskDocument,
            RiskDocumentStatus,
        )
        from app.modules.style_facts.fact_models import (
            FactItem,
            FactItemStatus,
        )
        from app.modules.style_facts.style_models import (
            AccountStyleProfile,
            StyleProfileStatus,
        )

        account = self._account(account_id)
        objective = self._session.scalar(
            select(ObjectiveProfile)
            .where(
                ObjectiveProfile.workspace_id == self._context.workspace_id,
                ObjectiveProfile.account_id == account.id,
            )
            .order_by(ObjectiveProfile.version.desc())
        )
        content = None
        if content_id is not None:
            content = self._session.scalar(
                select(Content).where(
                    Content.id == content_id,
                    Content.workspace_id == self._context.workspace_id,
                    Content.account_id == account.id,
                    Content.platform == account.platform,
                    Content.deleted_at.is_(None),
                )
            )
            if content is None:
                raise LookupError("content not found")
        has_snapshot = False
        has_cover = False
        if content is not None:
            has_snapshot = (
                self._session.scalar(
                    select(DataSnapshot.id).where(
                        DataSnapshot.workspace_id
                        == self._context.workspace_id,
                        DataSnapshot.content_id == content.id,
                        DataSnapshot.platform == account.platform,
                        DataSnapshot.confirmed.is_(True),
                    )
                )
                is not None
            )
            has_cover = (
                self._session.scalar(
                    select(ContentAsset.id).where(
                        ContentAsset.workspace_id
                        == self._context.workspace_id,
                        ContentAsset.content_id == content.id,
                        ContentAsset.category == AssetCategory.COVER,
                    )
                )
                is not None
            )
        return calculate_completeness(
            CompletenessInput(
                platform=account.platform.value,
                has_objective=objective is not None
                and bool(objective.objectives),
                has_metric_weights=objective is not None
                and bool(objective.metric_weights),
                has_benchmark=self._session.scalar(
                    select(BenchmarkProfile.id).where(
                        BenchmarkProfile.workspace_id
                        == self._context.workspace_id,
                        BenchmarkProfile.account_id == account.id,
                    )
                )
                is not None,
                has_column_campaign=self._session.scalar(
                    select(ColumnCampaign.id).where(
                        ColumnCampaign.workspace_id
                        == self._context.workspace_id,
                        ColumnCampaign.account_id == account.id,
                    )
                )
                is not None,
                has_confirmed_style=self._session.scalar(
                    select(AccountStyleProfile.id).where(
                        AccountStyleProfile.workspace_id
                        == self._context.workspace_id,
                        AccountStyleProfile.account_id == account.id,
                        AccountStyleProfile.status
                        == StyleProfileStatus.CONFIRMED,
                    )
                )
                is not None,
                has_confirmed_facts=self._session.scalar(
                    select(FactItem.id).where(
                        FactItem.workspace_id == self._context.workspace_id,
                        FactItem.status == FactItemStatus.CONFIRMED,
                    )
                )
                is not None,
                has_title=content is not None and bool(content.title.strip()),
                has_body=content is not None and bool(content.body.strip()),
                has_cover=has_cover,
                has_confirmed_snapshot=has_snapshot,
                has_active_risk_knowledge=self._session.scalar(
                    select(RiskDocument.id).where(
                        RiskDocument.platform == account.platform,
                        RiskDocument.status == RiskDocumentStatus.ACTIVE,
                        (
                            (RiskDocument.workspace_id.is_(None))
                            | (
                                RiskDocument.workspace_id
                                == self._context.workspace_id
                            )
                        ),
                    )
                )
                is not None,
                has_active_model=self._session.scalar(
                    select(ModelConfig.id).where(
                        ModelConfig.workspace_id == self._context.workspace_id,
                        ModelConfig.status.in_(
                            [
                                ModelConfigStatus.VERIFIED,
                                ModelConfigStatus.EXPERIMENTAL,
                            ]
                        ),
                    )
                )
                is not None,
                is_demo=self._context.role == "demo",
            )
        )

    def product_metrics(self) -> ProductMetrics:
        from app.modules.analysis.models import ProductEvent
        from app.modules.imports.models import ImportBatch, ImportBatchStatus
        from app.modules.metrics.models import DataSnapshot
        from app.modules.workspace.models import Workspace

        workspace = self._session.get(
            Workspace,
            self._context.workspace_id,
        )
        if workspace is None:
            raise LookupError("workspace not found")
        events = list(
            self._session.scalars(
                select(ProductEvent)
                .where(
                    ProductEvent.workspace_id == self._context.workspace_id,
                    ProductEvent.analytics_eligible.is_(True),
                )
                .order_by(
                    ProductEvent.server_occurred_at,
                    ProductEvent.id,
                )
            )
        )
        facts = [
            AnalyticsEventFact(
                event_id=event.id,
                event_name=event.event_name,
                workspace_id=event.workspace_id,
                platform=event.platform.value if event.platform else "",
                occurred_at=event.server_occurred_at,
                analytics_eligible=True,
            )
            for event in events
        ]
        durations: dict[tuple[str, str], list[int]] = {}
        imported_snapshot_ids: set[UUID] = set()
        for batch in self._session.scalars(
            select(ImportBatch).where(
                ImportBatch.workspace_id == self._context.workspace_id,
                ImportBatch.status == ImportBatchStatus.CONFIRMED,
                ImportBatch.confirmed_at.is_not(None),
            )
        ):
            assert batch.confirmed_at is not None
            durations.setdefault(
                (batch.platform.value, batch.source_kind.value),
                [],
            ).append(
                max(
                    0,
                    int(
                        (batch.confirmed_at - batch.created_at).total_seconds()
                    ),
                )
            )
            if batch.confirmation_result is not None:
                imported_snapshot_ids.update(
                    UUID(value)
                    for value in cast(
                        list[str],
                        batch.confirmation_result.get(
                            "snapshot_ids",
                            [],
                        ),
                    )
                )
        for snapshot in self._session.scalars(
            select(DataSnapshot).where(
                DataSnapshot.workspace_id == self._context.workspace_id,
                DataSnapshot.confirmed.is_(True),
                DataSnapshot.confirmed_at.is_not(None),
                DataSnapshot.analytics_eligible.is_(True),
            )
        ):
            if snapshot.id in imported_snapshot_ids:
                continue
            assert snapshot.confirmed_at is not None
            durations.setdefault(
                (snapshot.platform.value, snapshot.source.value),
                [],
            ).append(
                max(
                    0,
                    int(
                        (
                            snapshot.confirmed_at - snapshot.created_at
                        ).total_seconds()
                    ),
                )
            )
        latest_feedback: dict[tuple[UUID | None, UUID | None], str] = {}
        for event in events:
            if event.event_name == "analysis.feedback":
                latest_feedback[
                    (event.actor_id, event.analysis_run_id)
                ] = str(event.properties["rating"])
        feedback_counts = {"useful": 0, "not_useful": 0}
        for rating in latest_feedback.values():
            feedback_counts[rating] += 1
        saved_ids = {
            event.suggestion_id
            for event in events
            if event.event_name == "suggestion.saved"
        }
        adopted_ids = {
            event.suggestion_id
            for event in events
            if event.event_name == "suggestion.adopted"
        }
        generation_statuses = {
            "generated": 0,
            "adopted": 0,
            "edited": 0,
            "rejected": 0,
        }
        event_to_status = {
            "generation.completed": "generated",
            "generation.adopted": "adopted",
            "generation.edited": "edited",
            "generation.rejected": "rejected",
        }
        for event in events:
            status = event_to_status.get(event.event_name)
            if status:
                generation_statuses[status] += 1
        return ProductMetrics(
            first_analysis=calculate_first_analysis_duration(
                workspace_entered_at=workspace.created_at,
                events=facts,
            ),
            collection_durations=tuple(
                CollectionDuration(
                    platform=platform,
                    source=source,
                    sample_count=len(samples),
                    average_seconds=round(sum(samples) / len(samples), 3),
                )
                for (platform, source), samples in sorted(durations.items())
            ),
            analysis_feedback_latest=feedback_counts,
            suggestion_saved=len(saved_ids),
            suggestion_adopted=len(adopted_ids),
            suggestion_save_denominator=len(
                {
                    event.analysis_run_id
                    for event in events
                    if event.event_name == "analysis.viewed"
                }
            ),
            suggestion_adoption_rate=(
                round(len(adopted_ids) / len(saved_ids), 6)
                if saved_ids
                else None
            ),
            generation_statuses=generation_statuses,
        )

    def effective_loops(self) -> list[EffectiveWeeklyLoop]:
        from app.modules.analysis.models import ProductEvent
        from app.modules.content.account_models import Platform
        from app.modules.content.models import Content, ContentStatus
        from app.modules.metrics.models import DataSnapshot

        evidence_sets: list[LoopEvidence] = []
        for platform in Platform:
            content = self._session.scalar(
                select(Content)
                .where(
                    Content.workspace_id == self._context.workspace_id,
                    Content.platform == platform,
                    Content.status == ContentStatus.PUBLISHED,
                    Content.published_at.is_not(None),
                    Content.deleted_at.is_(None),
                )
                .order_by(Content.published_at, Content.id)
            )
            snapshot = self._session.scalar(
                select(DataSnapshot)
                .where(
                    DataSnapshot.workspace_id == self._context.workspace_id,
                    DataSnapshot.platform == platform,
                    DataSnapshot.confirmed.is_(True),
                    DataSnapshot.analytics_eligible.is_(True),
                )
                .order_by(DataSnapshot.confirmed_at, DataSnapshot.id)
            )
            if content is None or snapshot is None:
                continue
            event_rows = list(
                self._session.scalars(
                    select(ProductEvent).where(
                        ProductEvent.workspace_id
                        == self._context.workspace_id,
                        ProductEvent.platform == platform,
                        ProductEvent.analytics_eligible.is_(True),
                    )
                )
            )
            evidence_sets.append(
                LoopEvidence(
                    workspace_id=self._context.workspace_id,
                    platform=platform.value,
                    published_content_id=content.id,
                    published_at=content.published_at,
                    confirmed_snapshot_id=snapshot.id,
                    snapshot_confirmed_at=snapshot.confirmed_at,
                    snapshot_analytics_eligible=snapshot.analytics_eligible,
                    events=[
                        AnalyticsEventFact(
                            event_id=event.id,
                            event_name=event.event_name,
                            workspace_id=event.workspace_id,
                            platform=platform.value,
                            occurred_at=event.server_occurred_at,
                            analytics_eligible=event.analytics_eligible,
                        )
                        for event in event_rows
                    ],
                )
            )
        return derive_effective_weekly_loops(evidence_sets)
