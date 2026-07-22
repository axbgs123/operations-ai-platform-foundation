from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import utc_now
from app.core.security import WorkspaceContext
from app.modules.analysis.viral_models import (
    ViralCandidate,
    ViralCandidateStatus,
    ViralCategory,
    ViralLibraryItem,
    ViralThresholdProfile,
)
from app.modules.content.account_models import (
    BenchmarkProfile,
    ObjectiveProfile,
    Platform,
    PlatformAccount,
)
from app.modules.content.models import Content
from app.modules.metrics.benchmark import historical_percentile
from app.modules.metrics.definitions import get_metric_definitions
from app.modules.metrics.maturity import MaturityBucket
from app.modules.metrics.models import ContentType, DataSnapshot, MetricDefinition, SnapshotMetricValue
from app.modules.workspace.models import AuditLog
from app.modules.workspace.permissions import Permission, require_permission


class ViralThresholdRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: ViralCategory
    metric_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    minimum_value: Decimal = Field(ge=0)


class ViralThresholdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[ViralThresholdRule] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_rules(self) -> "ViralThresholdInput":
        identities = [(rule.category, rule.metric_key) for rule in self.rules]
        if len(identities) != len(set(identities)):
            raise ValueError("viral threshold rules must be unique")
        return self


class ViralThresholdRead(BaseModel):
    id: UUID
    workspace_id: UUID
    account_id: UUID
    version: int
    rules: list[ViralThresholdRule]
    objective_profile_id: UUID
    benchmark_profile_id: UUID


class ViralEvaluationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: Literal["video", "image_text"]
    maturity_bucket: Literal["1h", "24h", "72h", "7d"]


class ViralCandidateRead(BaseModel):
    id: UUID
    workspace_id: UUID
    account_id: UUID
    content_id: UUID
    snapshot_id: UUID
    title: str
    platform: Platform
    content_type: ContentType
    maturity_bucket: str
    category: ViralCategory
    metric_key: str
    actual_value: float
    percentile: float
    sample_count: int
    threshold_value: float
    threshold_profile_id: UUID
    threshold_profile_version: int
    objective_profile_id: UUID
    benchmark_profile_id: UUID
    sample_snapshot_ids: list[UUID]
    comparison_started_at: datetime
    comparison_ended_at: datetime
    reason: str
    status: ViralCandidateStatus


class ViralCandidateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_snapshot_ids: list[UUID]
    comparison_started_at: datetime
    comparison_ended_at: datetime
    algorithm_version: Literal["viral-candidate-v1"]


ShortLabel = Annotated[str, Field(min_length=1, max_length=80)]


class ViralConfirmationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_tags: list[ShortLabel] = Field(min_length=1, max_length=10)
    applicable_scenarios: list[ShortLabel] = Field(min_length=1, max_length=10)
    structure_summary: str = Field(min_length=1, max_length=1000)

    @field_validator("strategy_tags", "applicable_scenarios")
    @classmethod
    def normalize_labels(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("labels must contain visible characters")
        if len(normalized) != len(set(normalized)):
            raise ValueError("labels must be unique")
        return normalized

    @field_validator("structure_summary")
    @classmethod
    def normalize_summary(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("structure summary must contain visible characters")
        return normalized


class ViralRevocationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("revocation reason must contain visible characters")
        return normalized


class ViralLibraryItemRead(BaseModel):
    id: UUID
    workspace_id: UUID
    account_id: UUID
    candidate_id: UUID
    content_id: UUID
    title: str
    category: ViralCategory
    strategy_tags: list[str]
    applicable_scenarios: list[str]
    structure_summary: str
    confirmed_by: UUID | None
    confirmed_at: datetime
    active: bool
    generation_eligible: bool
    revoked_by: UUID | None
    revoked_at: datetime | None
    revocation_reason: str | None


@dataclass(frozen=True)
class ComparableSample:
    snapshot: DataSnapshot
    content: Content
    values: dict[str, Decimal]


CATEGORY_METRICS: dict[ViralCategory, frozenset[str]] = {
    ViralCategory.TRAFFIC: frozenset(
        {
            "impressions",
            "views",
            "cover_click_rate",
            "completion_rate_5s",
            "completion_rate",
            "average_watch_duration",
        }
    ),
    ViralCategory.ENGAGEMENT: frozenset(
        {"likes", "comments", "shares", "favorites", "engagement_rate"}
    ),
    ViralCategory.GROWTH: frozenset({"followers_gained"}),
    ViralCategory.CONVERSION: frozenset(
        {"profile_visits", "profile_visit_rate", "follow_conversion_rate"}
    ),
}
CATEGORY_OBJECTIVES = {
    ViralCategory.TRAFFIC: "reach",
    ViralCategory.ENGAGEMENT: "engagement",
    ViralCategory.GROWTH: "growth",
    ViralCategory.CONVERSION: "conversion",
}


class ViralService:
    def __init__(self, session: Session, context: WorkspaceContext) -> None:
        self._session = session
        self._context = context

    def _account(self, account_id: UUID, *, lock: bool = False) -> PlatformAccount:
        query = select(PlatformAccount).where(
            PlatformAccount.id == account_id,
            PlatformAccount.workspace_id == self._context.workspace_id,
        )
        if lock:
            query = query.with_for_update()
        account = self._session.scalar(query)
        if account is None:
            raise LookupError("account not found")
        return account

    def _metric_directions(self, account: PlatformAccount) -> dict[str, bool]:
        directions = {
            definition.key: definition.higher_is_better
            for content_type in ContentType
            for definition in get_metric_definitions(account.platform, content_type)
        }
        custom = self._session.execute(
            select(MetricDefinition.key, MetricDefinition.higher_is_better).where(
                MetricDefinition.workspace_id == self._context.workspace_id,
                MetricDefinition.platform == account.platform,
            )
        )
        for key, higher_is_better in custom:
            directions[key] = higher_is_better
        return directions

    def _configuration_profiles(
        self, account_id: UUID
    ) -> tuple[ObjectiveProfile, BenchmarkProfile]:
        objective = self._session.scalar(
            select(ObjectiveProfile)
            .where(
                ObjectiveProfile.workspace_id == self._context.workspace_id,
                ObjectiveProfile.account_id == account_id,
                ObjectiveProfile.is_account_default.is_(True),
            )
            .order_by(ObjectiveProfile.version.desc())
            .limit(1)
        )
        benchmark = self._session.scalar(
            select(BenchmarkProfile)
            .where(
                BenchmarkProfile.workspace_id == self._context.workspace_id,
                BenchmarkProfile.account_id == account_id,
                BenchmarkProfile.is_account_default.is_(True),
            )
            .order_by(BenchmarkProfile.version.desc())
            .limit(1)
        )
        if objective is None or benchmark is None:
            raise LookupError("account configuration not found")
        return objective, benchmark

    def configure_thresholds(
        self,
        account_id: UUID,
        data: ViralThresholdInput,
    ) -> ViralThresholdProfile:
        require_permission(self._context.role, Permission.MANAGE_MEMBERS)
        account = self._account(account_id, lock=True)
        objective, benchmark = self._configuration_profiles(account.id)
        directions = self._metric_directions(account)
        custom_keys = set(
            self._session.scalars(
                select(MetricDefinition.key).where(
                    MetricDefinition.workspace_id == self._context.workspace_id,
                    MetricDefinition.platform == account.platform,
                )
            )
        )
        invalid = {rule.metric_key for rule in data.rules} - directions.keys()
        if invalid:
            raise ValueError(f"incompatible viral metric(s): {', '.join(sorted(invalid))}")
        for rule in data.rules:
            if not directions[rule.metric_key]:
                raise ValueError(
                    f"lower-is-better metric cannot use an absolute minimum: {rule.metric_key}"
                )
            if (
                rule.metric_key not in custom_keys
                and rule.metric_key not in CATEGORY_METRICS[rule.category]
            ):
                raise ValueError(
                    f"metric {rule.metric_key} is not valid for {rule.category.value}"
                )
            if CATEGORY_OBJECTIVES[rule.category] not in objective.objectives:
                raise ValueError(
                    f"viral category {rule.category.value} is not an enabled objective"
                )
        latest_version = self._session.scalar(
            select(func.max(ViralThresholdProfile.version)).where(
                ViralThresholdProfile.account_id == account.id,
                ViralThresholdProfile.workspace_id == self._context.workspace_id,
            )
        )
        profile = ViralThresholdProfile(
            workspace_id=self._context.workspace_id,
            account_id=account.id,
            version=(latest_version or 0) + 1,
            rules=[rule.model_dump(mode="json") for rule in data.rules],
            objective_profile_id=objective.id,
            benchmark_profile_id=benchmark.id,
            created_by=self._context.member_id,
        )
        self._session.add(profile)
        self._session.flush()
        self._session.add(
            AuditLog(
                workspace_id=self._context.workspace_id,
                member_id=self._context.member_id,
                action="viral_threshold.configured",
                resource_type="viral_threshold_profile",
                resource_id=profile.id,
                details={"version": profile.version},
            )
        )
        self._session.flush()
        return profile

    def _latest_threshold(self, account_id: UUID) -> ViralThresholdProfile:
        profile = self._session.scalar(
            select(ViralThresholdProfile)
            .where(
                ViralThresholdProfile.workspace_id == self._context.workspace_id,
                ViralThresholdProfile.account_id == account_id,
            )
            .order_by(ViralThresholdProfile.version.desc())
            .limit(1)
            .with_for_update()
        )
        if profile is None:
            raise LookupError("viral thresholds not configured")
        return profile

    def current_threshold(self, account_id: UUID) -> ViralThresholdProfile | None:
        require_permission(self._context.role, Permission.READ_CONTENT)
        self._account(account_id)
        return self._session.scalar(
            select(ViralThresholdProfile)
            .where(
                ViralThresholdProfile.workspace_id == self._context.workspace_id,
                ViralThresholdProfile.account_id == account_id,
            )
            .order_by(ViralThresholdProfile.version.desc())
            .limit(1)
        )

    def _samples(
        self,
        account: PlatformAccount,
        content_type: ContentType,
        maturity_bucket: MaturityBucket,
        limit: int,
    ) -> list[ComparableSample]:
        ranked = (
            select(
                DataSnapshot.id.label("snapshot_id"),
                func.row_number().over(
                    partition_by=DataSnapshot.content_id,
                    order_by=(DataSnapshot.collected_at.desc(), DataSnapshot.id.desc()),
                ).label("snapshot_rank"),
            )
            .where(
                DataSnapshot.workspace_id == self._context.workspace_id,
                DataSnapshot.account_id == account.id,
                DataSnapshot.platform == account.platform,
                DataSnapshot.content_type == content_type,
                DataSnapshot.maturity_bucket == maturity_bucket.value,
                DataSnapshot.confirmed.is_(True),
            )
            .subquery()
        )
        latest = list(
            self._session.execute(
                select(DataSnapshot, Content)
                .join(Content, Content.id == DataSnapshot.content_id)
                .join(ranked, ranked.c.snapshot_id == DataSnapshot.id)
                .where(
                    ranked.c.snapshot_rank == 1,
                    Content.workspace_id == self._context.workspace_id,
                    Content.account_id == account.id,
                    Content.platform == account.platform,
                    Content.content_type == content_type,
                    Content.deleted_at.is_(None),
                )
                .order_by(Content.published_at.desc(), DataSnapshot.id.desc())
                .limit(limit)
            )
        )
        snapshot_ids = [snapshot.id for snapshot, _ in latest]
        by_snapshot: dict[UUID, dict[str, Decimal]] = {
            snapshot_id: {} for snapshot_id in snapshot_ids
        }
        if snapshot_ids:
            rows = self._session.execute(
                select(
                    SnapshotMetricValue.snapshot_id,
                    SnapshotMetricValue.metric_key,
                    SnapshotMetricValue.normalized_value,
                ).where(
                    SnapshotMetricValue.workspace_id == self._context.workspace_id,
                    SnapshotMetricValue.snapshot_id.in_(snapshot_ids),
                    SnapshotMetricValue.eligible_for_benchmark.is_(True),
                    SnapshotMetricValue.normalized_value.is_not(None),
                )
            )
            for snapshot_id, metric_key, value in rows:
                if value is not None:
                    by_snapshot[snapshot_id][metric_key] = value
        return [
            ComparableSample(snapshot, content, by_snapshot[snapshot.id])
            for snapshot, content in latest
        ]

    def evaluate(
        self,
        account_id: UUID,
        data: ViralEvaluationInput,
    ) -> list[ViralCandidate]:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        account = self._account(account_id)
        content_type = ContentType(data.content_type)
        maturity_bucket = MaturityBucket(data.maturity_bucket)
        threshold_profile = self._latest_threshold(account.id)
        benchmark_profile = self._session.get(
            BenchmarkProfile, threshold_profile.benchmark_profile_id
        )
        if benchmark_profile is None:
            raise LookupError("benchmark profile not found")
        samples = self._samples(
            account,
            content_type,
            maturity_bucket,
            benchmark_profile.sample_size,
        )
        created: list[ViralCandidate] = []
        for rule_data in threshold_profile.rules:
            rule = ViralThresholdRule.model_validate(rule_data)
            valued = [
                sample
                for sample in samples
                if rule.metric_key in sample.values
                and sample.content.published_at is not None
            ]
            if len(valued) < 10:
                continue
            history = [sample.values[rule.metric_key] for sample in valued]
            for sample in valued:
                value = sample.values[rule.metric_key]
                rank = historical_percentile(value, history)
                if rank < Decimal("0.9") or value < rule.minimum_value:
                    continue
                existing = self._session.scalar(
                    select(ViralCandidate).where(
                        ViralCandidate.threshold_profile_id == threshold_profile.id,
                        ViralCandidate.content_id == sample.content.id,
                        ViralCandidate.category == rule.category,
                        ViralCandidate.metric_key == rule.metric_key,
                    )
                )
                if existing is not None:
                    created.append(existing)
                    continue
                candidate = ViralCandidate(
                    workspace_id=self._context.workspace_id,
                    account_id=account.id,
                    content_id=sample.content.id,
                    snapshot_id=sample.snapshot.id,
                    platform=account.platform,
                    content_type=content_type,
                    maturity_bucket=maturity_bucket.value,
                    category=rule.category,
                    metric_key=rule.metric_key,
                    actual_value=value,
                    percentile=float(rank),
                    sample_count=len(valued),
                    threshold_value=rule.minimum_value,
                    threshold_profile_id=threshold_profile.id,
                    threshold_profile_version=threshold_profile.version,
                    objective_profile_id=threshold_profile.objective_profile_id,
                    benchmark_profile_id=threshold_profile.benchmark_profile_id,
                    evidence=ViralCandidateEvidence(
                        sample_snapshot_ids=[item.snapshot.id for item in valued],
                        comparison_started_at=min(
                            published_at
                            for item in valued
                            if (published_at := item.content.published_at) is not None
                        ),
                        comparison_ended_at=max(
                            published_at
                            for item in valued
                            if (published_at := item.content.published_at) is not None
                        ),
                        algorithm_version="viral-candidate-v1",
                    ).model_dump(mode="json"),
                    reason=(
                        f"{rule.metric_key} 进入账号历史前 10%，"
                        f"且达到绝对门槛 {rule.minimum_value}."
                    ),
                )
                self._session.add(candidate)
                self._session.flush()
                created.append(candidate)
        return created

    def list_candidates(self, account_id: UUID) -> list[ViralCandidate]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        self._account(account_id)
        return list(
            self._session.scalars(
                select(ViralCandidate)
                .where(
                    ViralCandidate.workspace_id == self._context.workspace_id,
                    ViralCandidate.account_id == account_id,
                )
                .order_by(ViralCandidate.created_at.desc(), ViralCandidate.id.desc())
            )
        )

    def confirm(
        self,
        candidate_id: UUID,
        data: ViralConfirmationInput,
    ) -> ViralLibraryItem:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        candidate = self._session.scalar(
            select(ViralCandidate).where(
                ViralCandidate.id == candidate_id,
                ViralCandidate.workspace_id == self._context.workspace_id,
            ).with_for_update()
        )
        if candidate is None:
            raise LookupError("viral candidate not found")
        if candidate.status != ViralCandidateStatus.RECOMMENDED:
            raise ValueError("viral candidate is no longer confirmable")
        existing = self._session.scalar(
            select(ViralLibraryItem).where(
                ViralLibraryItem.candidate_id == candidate.id
            )
        )
        if existing is not None:
            raise ValueError("viral candidate already has a library item")
        item = ViralLibraryItem(
            workspace_id=self._context.workspace_id,
            account_id=candidate.account_id,
            candidate_id=candidate.id,
            content_id=candidate.content_id,
            category=candidate.category,
            strategy_tags=data.strategy_tags,
            applicable_scenarios=data.applicable_scenarios,
            structure_summary=data.structure_summary,
            confirmed_by=self._context.member_id,
        )
        candidate.status = ViralCandidateStatus.CONFIRMED
        self._session.add(item)
        self._session.flush()
        self._session.add(
            AuditLog(
                workspace_id=self._context.workspace_id,
                member_id=self._context.member_id,
                action="viral_library.confirmed",
                resource_type="viral_library_item",
                resource_id=item.id,
                details={"candidate_id": str(candidate.id)},
            )
        )
        self._session.flush()
        return item

    def revoke(
        self,
        item_id: UUID,
        data: ViralRevocationInput,
    ) -> ViralLibraryItem:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        item = self._session.scalar(
            select(ViralLibraryItem).where(
                ViralLibraryItem.id == item_id,
                ViralLibraryItem.workspace_id == self._context.workspace_id,
            ).with_for_update()
        )
        if item is None:
            raise LookupError("viral library item not found")
        if item.revoked_at is not None:
            raise ValueError("viral library item already revoked")
        candidate = self._session.get(ViralCandidate, item.candidate_id)
        item.revoked_at = utc_now()
        item.revoked_by = self._context.member_id
        item.revocation_reason = data.reason
        if candidate is not None:
            candidate.status = ViralCandidateStatus.REVOKED
        self._session.add(
            AuditLog(
                workspace_id=self._context.workspace_id,
                member_id=self._context.member_id,
                action="viral_library.revoked",
                resource_type="viral_library_item",
                resource_id=item.id,
                details={"reason": data.reason},
            )
        )
        self._session.flush()
        return item

    def library_items(
        self, account_id: UUID, *, active_only: bool = False
    ) -> list[ViralLibraryItem]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        self._account(account_id)
        query = (
            select(ViralLibraryItem)
            .join(Content, Content.id == ViralLibraryItem.content_id)
            .join(ViralCandidate, ViralCandidate.id == ViralLibraryItem.candidate_id)
            .where(
                ViralLibraryItem.workspace_id == self._context.workspace_id,
                ViralLibraryItem.account_id == account_id,
            )
        )
        if active_only:
            query = query.where(
                ViralLibraryItem.revoked_at.is_(None),
                ViralCandidate.status == ViralCandidateStatus.CONFIRMED,
                Content.deleted_at.is_(None),
            )
        return list(
            self._session.scalars(
                query.order_by(
                    ViralLibraryItem.confirmed_at.desc(),
                    ViralLibraryItem.id.desc(),
                )
            )
        )

    def library_payload(self, item: ViralLibraryItem) -> ViralLibraryItemRead:
        content = self._session.get(Content, item.content_id)
        candidate = self._session.get(ViralCandidate, item.candidate_id)
        return ViralLibraryItemRead(
            id=item.id,
            workspace_id=item.workspace_id,
            account_id=item.account_id,
            candidate_id=item.candidate_id,
            content_id=item.content_id,
            title=content.title if content else "",
            category=item.category,
            strategy_tags=item.strategy_tags,
            applicable_scenarios=item.applicable_scenarios,
            structure_summary=item.structure_summary,
            confirmed_by=item.confirmed_by,
            confirmed_at=item.confirmed_at,
            active=item.revoked_at is None,
            generation_eligible=(
                item.revoked_at is None
                and content is not None
                and content.deleted_at is None
                and candidate is not None
                and candidate.status == ViralCandidateStatus.CONFIRMED
            ),
            revoked_by=item.revoked_by,
            revoked_at=item.revoked_at,
            revocation_reason=item.revocation_reason,
        )

    def candidate_payload(self, candidate: ViralCandidate) -> ViralCandidateRead:
        content = self._session.get(Content, candidate.content_id)
        evidence = ViralCandidateEvidence.model_validate(candidate.evidence)
        return ViralCandidateRead(
            id=candidate.id,
            workspace_id=candidate.workspace_id,
            account_id=candidate.account_id,
            content_id=candidate.content_id,
            snapshot_id=candidate.snapshot_id,
            title=content.title if content else "",
            platform=candidate.platform,
            content_type=candidate.content_type,
            maturity_bucket=candidate.maturity_bucket,
            category=candidate.category,
            metric_key=candidate.metric_key,
            actual_value=float(candidate.actual_value),
            percentile=candidate.percentile,
            sample_count=candidate.sample_count,
            threshold_value=float(candidate.threshold_value),
            threshold_profile_id=candidate.threshold_profile_id,
            threshold_profile_version=candidate.threshold_profile_version,
            objective_profile_id=candidate.objective_profile_id,
            benchmark_profile_id=candidate.benchmark_profile_id,
            sample_snapshot_ids=evidence.sample_snapshot_ids,
            comparison_started_at=evidence.comparison_started_at,
            comparison_ended_at=evidence.comparison_ended_at,
            reason=candidate.reason,
            status=candidate.status,
        )
