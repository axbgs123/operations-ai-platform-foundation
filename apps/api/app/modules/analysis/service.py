import hashlib
import json
from datetime import timedelta
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.core.database import utc_now
from app.core.config import get_settings
from app.modules.analysis.features import (
    AnalysisEvidenceBundle,
    BenchmarkEvidenceInput,
    ComparableContentEvidenceInput,
    ContentEvidenceInput,
    CoverAssetEvidenceInput,
    MetricEvidenceInput,
    SnapshotEvidenceInput,
    build_analysis_evidence,
)
from app.modules.analysis.models import (
    AccountAnalysisSetting,
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisSuggestion,
)
from app.modules.analytics.events import EventName, EventService, ProductEventInput
from app.modules.analysis.schemas import (
    AnalysisAdapter,
    AnalysisReport,
    InvalidAnalysisOutput,
)
from app.modules.models.adapter_factory import ModelBinding
from app.modules.models.capabilities import Capability
from app.modules.models.catalog import get_catalog_entry
from app.modules.models.config_service import (
    ModelConfigurationRequired,
    ModelConfigService,
    SecretCipher,
)
from app.modules.models.adapters.qianwen import (
    ModelProviderError,
    safe_model_error_message,
)
from app.modules.content.account_models import BenchmarkProfile, ObjectiveProfile, PlatformAccount
from app.modules.content.models import AssetCategory, Content, ContentAsset
from app.modules.metrics.benchmark import (
    BenchmarkInput,
    BenchmarkRange,
    BenchmarkRangeKind,
    calculate_benchmark,
)
from app.modules.metrics.benchmark_tasks import BENCHMARK_ALGORITHM_VERSION
from app.modules.metrics.maturity import MaturityBucket
from app.modules.metrics.models import BenchmarkRun, DataSnapshot, SnapshotMetricValue
from app.modules.workspace.permissions import Permission, require_permission


ANALYSIS_PROMPT_VERSION = "analysis-prompt-v1"
ANALYSIS_ALGORITHM_VERSION = "analysis-v1"


class AnalysisVersionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: UUID
    account_id: UUID
    content_id: UUID
    benchmark_run_id: UUID
    snapshot_ids: list[UUID]
    model_version: str
    model_config_id: UUID | None = None
    model_provider: str = "mock"
    provider_contract_version: str = "mock-structured-v1"
    model_config_version: str = "legacy"
    prompt_version: str
    algorithm_version: str
    benchmark_algorithm_version: str
    trigger_kind: Literal["manual", "auto"]
    requested_by: UUID | None = None


def resolve_analysis_model_binding(
    *,
    session: Session,
    context: WorkspaceContext,
    cipher: SecretCipher,
    mock_mode: bool,
) -> tuple[UUID | None, ModelBinding]:
    if mock_mode:
        return None, ModelBinding(
            provider="mock",
            model_id="mock-analysis-v1",
            contract_version="mock-structured-v1",
            configuration_version="mock-static-v1",
        )
    config_service = ModelConfigService(
        session,
        context,
        cipher=cipher,
    )
    try:
        config = config_service.resolve(
            {Capability.TEXT},
            provider="qianwen",
        )
    except ModelConfigurationRequired:
        config = config_service.resolve(
            {Capability.TEXT},
            provider="openai_compatible",
        )
    try:
        catalog = get_catalog_entry(config.provider, config.model_id)
    except LookupError:
        catalog = None
    contract_version = (
        catalog.contract_version
        if catalog is not None
        else "openai-compatible-chat-json-v1"
    )
    return config.id, ModelBinding(
        provider=config.provider,
        model_id=config.model_id,
        contract_version=contract_version,
        configuration_version=config.updated_at.isoformat(),
    )


def analysis_cache_key(
    bundle: AnalysisEvidenceBundle,
    context: AnalysisVersionContext,
) -> str:
    semantic_bundle = bundle.model_dump(mode="json")
    semantic_bundle["benchmark"]["id"] = "current-benchmark"
    for item in semantic_bundle["items"]:
        if item["kind"] == "benchmark":
            item["id"] = item["id"].split(":metric:", maxsplit=1)[-1]
            item["source_id"] = None
    cache_input = {
        "bundle": semantic_bundle,
        "model_config_id": str(context.model_config_id),
        "model_provider": context.model_provider,
        "model_version": context.model_version,
        "provider_contract_version": context.provider_contract_version,
        "model_config_version": context.model_config_version,
        "prompt_version": context.prompt_version,
        "algorithm_version": context.algorithm_version,
        "benchmark_algorithm_version": context.benchmark_algorithm_version,
    }
    canonical = json.dumps(
        cache_input,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def execute_bundle_analysis(
    session: Session,
    bundle: AnalysisEvidenceBundle,
    context: AnalysisVersionContext,
    adapter: AnalysisAdapter,
) -> AnalysisRun:
    cache_key = analysis_cache_key(bundle, context)
    cached = session.scalar(
        select(AnalysisRun).where(
            AnalysisRun.workspace_id == context.workspace_id,
            AnalysisRun.content_id == context.content_id,
            AnalysisRun.cache_key == cache_key,
            AnalysisRun.status == AnalysisRunStatus.SUCCEEDED,
        )
    )
    if cached is not None:
        return cached

    run = AnalysisRun(
        workspace_id=context.workspace_id,
        account_id=context.account_id,
        content_id=context.content_id,
        benchmark_run_id=context.benchmark_run_id,
        snapshot_ids=[str(snapshot_id) for snapshot_id in context.snapshot_ids],
        status=AnalysisRunStatus.RUNNING,
        trigger_kind=context.trigger_kind,
        cache_key=cache_key,
        evidence_bundle=bundle.model_dump(mode="json"),
        report=None,
        error_code=None,
        error_message=None,
        model_version=context.model_version,
        model_config_id=context.model_config_id,
        model_provider=context.model_provider,
        provider_contract_version=context.provider_contract_version,
        model_config_version=context.model_config_version,
        prompt_version=context.prompt_version,
        algorithm_version=context.algorithm_version,
        benchmark_algorithm_version=context.benchmark_algorithm_version,
        requested_by=context.requested_by,
        completed_at=None,
    )
    session.add(run)
    session.flush()
    return _complete_run(session, run, bundle, adapter)


def _complete_run(
    session: Session,
    run: AnalysisRun,
    bundle: AnalysisEvidenceBundle,
    adapter: AnalysisAdapter,
) -> AnalysisRun:
    run.status = AnalysisRunStatus.RUNNING
    session.flush()
    record_analysis_processing_started(session, run)
    try:
        report = adapter.analyze(bundle)
        report.validate_references(bundle)
    except ModelProviderError as error:
        return persist_analysis_failure(
            session,
            run.id,
            error_code=error.code.value,
            error_message=safe_model_error_message(error.code),
        )
    except (InvalidAnalysisOutput, ValueError):
        return persist_analysis_failure(
            session,
            run.id,
            error_code="MODEL_INVALID_RESPONSE",
            error_message="模型返回内容未通过结构或证据校验。",
        )
    return persist_analysis_success(session, run.id, report)


def record_analysis_processing_started(
    session: Session,
    run: AnalysisRun,
) -> None:
    if (
        session.scalar(
            select(PlatformAccount.id).where(
                PlatformAccount.id == run.account_id,
                PlatformAccount.workspace_id == run.workspace_id,
            )
        )
        is not None
    ):
        EventService(
            session,
            WorkspaceContext(
                workspace_id=run.workspace_id,
                member_id=run.requested_by,
                role="editor",
            ),
        ).record(
            ProductEventInput(
                event_name=EventName.ANALYSIS_PROCESSING_STARTED,
                idempotency_key=f"analysis-processing-started:{run.id}",
                analysis_run_id=run.id,
                provider_mode=(
                    "mock" if run.model_version.startswith("mock") else "real"
                ),
            )
        )
        session.flush()


def persist_analysis_failure(
    session: Session,
    run_id: UUID,
    *,
    error_code: str,
    error_message: str,
) -> AnalysisRun:
    run = session.scalar(
        select(AnalysisRun).where(AnalysisRun.id == run_id).with_for_update()
    )
    if run is None:
        raise LookupError("analysis run not found")
    if run.status in {AnalysisRunStatus.SUCCEEDED, AnalysisRunStatus.FAILED}:
        return run
    run.status = AnalysisRunStatus.FAILED
    run.report = None
    run.error_code = error_code
    run.error_message = error_message
    run.completed_at = utc_now()
    run.next_attempt_at = None
    run.lease_expires_at = None
    session.flush()
    return run


def persist_analysis_success(
    session: Session,
    run_id: UUID,
    report: AnalysisReport,
) -> AnalysisRun:
    run = session.scalar(
        select(AnalysisRun).where(AnalysisRun.id == run_id).with_for_update()
    )
    if run is None:
        raise LookupError("analysis run not found")
    if run.status in {AnalysisRunStatus.SUCCEEDED, AnalysisRunStatus.FAILED}:
        return run
    bundle = AnalysisEvidenceBundle.model_validate(run.evidence_bundle)
    try:
        report.validate_references(bundle)
    except ValueError:
        return persist_analysis_failure(
            session,
            run.id,
            error_code="MODEL_INVALID_RESPONSE",
            error_message="模型返回内容未通过结构或证据校验。",
        )
    run.status = AnalysisRunStatus.SUCCEEDED
    run.report = report.model_dump(mode="json")
    run.error_code = None
    run.error_message = None
    run.completed_at = utc_now()
    run.next_attempt_at = None
    run.lease_expires_at = None
    session.flush()
    if (
        session.scalar(
            select(PlatformAccount.id).where(
                PlatformAccount.id == run.account_id,
                PlatformAccount.workspace_id == run.workspace_id,
            )
        )
        is not None
    ):
        EventService(
            session,
            WorkspaceContext(
                workspace_id=run.workspace_id,
                member_id=run.requested_by,
                role="editor",
            ),
        ).record(
            ProductEventInput(
                event_name=EventName.ANALYSIS_COMPLETED,
                idempotency_key=f"analysis-completed:{run.id}",
                analysis_run_id=run.id,
                properties={"status": "succeeded"},
                provider_mode=(
                    "mock" if run.model_version.startswith("mock") else "real"
                ),
            )
        )
    session.flush()
    return run


def process_analysis_run(
    session: Session,
    run_id: UUID,
    adapter: AnalysisAdapter,
) -> AnalysisRun:
    run = session.scalar(
        select(AnalysisRun).where(AnalysisRun.id == run_id).with_for_update()
    )
    if run is None:
        raise LookupError("analysis run not found")
    if run.status in {AnalysisRunStatus.SUCCEEDED, AnalysisRunStatus.FAILED}:
        return run
    bundle = AnalysisEvidenceBundle.model_validate(run.evidence_bundle)
    return _complete_run(session, run, bundle, adapter)


def lease_recoverable_analysis_runs(
    session: Session,
    *,
    limit: int = 100,
) -> list[UUID]:
    stale_before = utc_now() - timedelta(minutes=5)
    now = utc_now()
    runs = list(
        session.scalars(
            select(AnalysisRun)
            .where(
                or_(
                    and_(
                        AnalysisRun.status == AnalysisRunStatus.PENDING,
                        or_(
                            AnalysisRun.next_attempt_at.is_(None),
                            AnalysisRun.next_attempt_at <= now,
                        ),
                        or_(
                            AnalysisRun.lease_expires_at.is_(None),
                            AnalysisRun.lease_expires_at <= now,
                        ),
                    ),
                    and_(
                        AnalysisRun.status == AnalysisRunStatus.RUNNING,
                        AnalysisRun.updated_at <= stale_before,
                    ),
                )
            )
            .order_by(AnalysisRun.created_at, AnalysisRun.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    lease_until = now + timedelta(minutes=5)
    for run in runs:
        if run.status == AnalysisRunStatus.RUNNING:
            run.status = AnalysisRunStatus.PENDING
        run.lease_expires_at = lease_until
    session.flush()
    return [run.id for run in runs]


def begin_analysis_attempt(session: Session, run_id: UUID) -> bool:
    run = session.scalar(
        select(AnalysisRun).where(AnalysisRun.id == run_id).with_for_update()
    )
    if run is None:
        raise LookupError("analysis run not found")
    if run.status != AnalysisRunStatus.PENDING:
        return False
    if run.next_attempt_at is not None and run.next_attempt_at > utc_now():
        return False
    run.status = AnalysisRunStatus.RUNNING
    run.attempt_count += 1
    run.next_attempt_at = None
    run.lease_expires_at = None
    session.flush()
    return True


def record_analysis_provider_failure(session: Session, run_id: UUID) -> None:
    run = session.scalar(
        select(AnalysisRun).where(AnalysisRun.id == run_id).with_for_update()
    )
    if run is None or run.status in {
        AnalysisRunStatus.SUCCEEDED,
        AnalysisRunStatus.FAILED,
    }:
        return
    if run.attempt_count >= 3:
        run.status = AnalysisRunStatus.FAILED
        run.error_code = "MODEL_PROVIDER_UNAVAILABLE"
        run.error_message = "模型服务暂时不可用，请稍后重试。"
        run.completed_at = utc_now()
        run.next_attempt_at = None
        run.lease_expires_at = None
    else:
        run.status = AnalysisRunStatus.PENDING
        run.error_code = None
        run.error_message = None
        run.next_attempt_at = utc_now() + timedelta(
            seconds=2 ** run.attempt_count
        )
        run.lease_expires_at = None
    session.flush()


def persist_analysis_terminal_failure(
    session: Session,
    run_id: UUID,
    *,
    error_code: str,
    error_message: str,
) -> AnalysisRun:
    run = session.scalar(
        select(AnalysisRun).where(AnalysisRun.id == run_id).with_for_update()
    )
    if run is None:
        raise LookupError("analysis run not found")
    if run.status in {
        AnalysisRunStatus.SUCCEEDED,
        AnalysisRunStatus.FAILED,
    }:
        return run
    run.status = AnalysisRunStatus.FAILED
    run.error_code = error_code
    run.error_message = error_message
    run.completed_at = utc_now()
    run.next_attempt_at = None
    run.lease_expires_at = None
    session.flush()
    return run


class AnalysisService:
    def __init__(self, session: Session, context: WorkspaceContext) -> None:
        self.session = session
        self.context = context

    def _content(self, content_id: UUID, *, mutation: bool) -> Content:
        require_permission(
            self.context.role,
            Permission.WRITE_CONTENT if mutation else Permission.READ_CONTENT,
        )
        content = self.session.scalar(
            select(Content).where(
                Content.id == content_id,
                Content.workspace_id == self.context.workspace_id,
                Content.deleted_at.is_(None),
            )
        )
        if content is None:
            raise LookupError("content not found")
        return content

    def _account(self, account_id: UUID, *, mutation: bool) -> PlatformAccount:
        require_permission(
            self.context.role,
            Permission.WRITE_CONTENT if mutation else Permission.READ_CONTENT,
        )
        account = self.session.scalar(
            select(PlatformAccount).where(
                PlatformAccount.id == account_id,
                PlatformAccount.workspace_id == self.context.workspace_id,
            )
        )
        if account is None:
            raise LookupError("account not found")
        return account

    def _bundle(self, content: Content) -> AnalysisEvidenceBundle:
        snapshots = list(
            self.session.scalars(
                select(DataSnapshot)
                .where(
                    DataSnapshot.workspace_id == content.workspace_id,
                    DataSnapshot.content_id == content.id,
                    DataSnapshot.confirmed.is_(True),
                )
                .order_by(DataSnapshot.collected_at, DataSnapshot.id)
            )
        )
        if not snapshots:
            raise ValueError("analysis requires at least one confirmed snapshot")
        latest = snapshots[-1]
        profile = self.session.get(BenchmarkProfile, content.benchmark_profile_id)
        objective = self.session.get(ObjectiveProfile, content.objective_profile_id)
        if profile is None or objective is None:
            raise LookupError("content configuration not found")
        benchmark_result = calculate_benchmark(
            self.session,
            BenchmarkInput(
                workspace_id=content.workspace_id,
                platform=content.platform,
                account_id=content.account_id,
                content_type=content.content_type,
                maturity_bucket=MaturityBucket(latest.maturity_bucket),
                range=BenchmarkRange(
                    kind=BenchmarkRangeKind.LATEST_N,
                    latest_n=profile.sample_size,
                ),
                version=BENCHMARK_ALGORITHM_VERSION,
            ),
            weights={
                key: Decimal(str(value))
                for key, value in objective.metric_weights.items()
            },
        )
        benchmark = self.session.get(BenchmarkRun, benchmark_result.run_id)
        assert benchmark is not None
        metric_rows = list(
            self.session.scalars(
                select(SnapshotMetricValue).where(
                    SnapshotMetricValue.snapshot_id.in_([row.id for row in snapshots])
                )
            )
        )
        metrics_by_snapshot: dict[UUID, list[MetricEvidenceInput]] = {}
        for metric in metric_rows:
            value = metric.normalized_value
            if value is not None:
                metrics_by_snapshot.setdefault(metric.snapshot_id, []).append(
                    MetricEvidenceInput(key=metric.metric_key, value=str(value))
                )
        covers = list(
            self.session.scalars(
                select(ContentAsset).where(
                    ContentAsset.content_id == content.id,
                    ContentAsset.workspace_id == content.workspace_id,
                    ContentAsset.category == AssetCategory.COVER,
                )
            )
        )
        comparisons: list[ComparableContentEvidenceInput] = []
        comparison_snapshot_ids = [
            UUID(value)
            for value in benchmark.sample_snapshot_ids
            if UUID(value) not in {snapshot.id for snapshot in snapshots}
        ]
        percentile_values = cast(
            dict[str, dict[str, str]], benchmark.percentile_values
        )
        if comparison_snapshot_ids and percentile_values:
            weighted_metrics = {
                key: Decimal(str(value))
                for key, value in benchmark.weights.items()
                if key in percentile_values
            }
            comparison_metric = (
                max(
                    weighted_metrics,
                    key=lambda key: (weighted_metrics[key], key),
                )
                if weighted_metrics
                else sorted(percentile_values)[0]
            )
            thresholds = percentile_values[comparison_metric]
            median = Decimal(str(thresholds["median"]))
            p90 = Decimal(str(thresholds["p90"]))
            comparison_rows = self.session.execute(
                select(
                    Content.id,
                    Content.title,
                    DataSnapshot.id,
                    SnapshotMetricValue.normalized_value,
                )
                .join(DataSnapshot, DataSnapshot.content_id == Content.id)
                .join(
                    SnapshotMetricValue,
                    SnapshotMetricValue.snapshot_id == DataSnapshot.id,
                )
                .where(
                    Content.workspace_id == content.workspace_id,
                    Content.account_id == content.account_id,
                    Content.platform == content.platform,
                    Content.content_type == content.content_type,
                    DataSnapshot.id.in_(comparison_snapshot_ids),
                    SnapshotMetricValue.metric_key == comparison_metric,
                    SnapshotMetricValue.normalized_value.is_not(None),
                )
                .order_by(Content.id, DataSnapshot.id)
            )
            high: list[ComparableContentEvidenceInput] = []
            low: list[ComparableContentEvidenceInput] = []
            for other_content_id, title, snapshot_id, normalized_value in comparison_rows:
                assert normalized_value is not None
                band: Literal["high", "low"] | None = (
                    "high"
                    if normalized_value >= p90
                    else "low"
                    if normalized_value <= median
                    else None
                )
                if band is None:
                    continue
                candidate = ComparableContentEvidenceInput(
                    content_id=other_content_id,
                    snapshot_id=snapshot_id,
                    title=title,
                    performance_band=band,
                    metric_key=comparison_metric,
                    metric_value=str(normalized_value),
                    similarity_basis="同账号、平台、内容类型与数据成熟度",
                )
                (high if band == "high" else low).append(candidate)
            comparisons = high[:3] + low[:3]
        return build_analysis_evidence(
            ContentEvidenceInput(
                id=content.id,
                title=content.published_title or content.title,
                body=content.published_body or content.body,
                cover_asset_ids=[asset.id for asset in covers],
                cover_asset_metadata=[
                    CoverAssetEvidenceInput(
                        id=asset.id,
                        object_key=asset.object_key,
                        file_name=asset.file_name,
                        mime_type=asset.mime_type,
                        size=asset.size,
                    )
                    for asset in covers
                ],
            ),
            [
                SnapshotEvidenceInput(
                    id=snapshot.id,
                    collected_at=snapshot.collected_at,
                    maturity_bucket=cast(
                        Literal["1h", "24h", "72h", "7d"],
                        snapshot.maturity_bucket,
                    ),
                    metrics=metrics_by_snapshot.get(snapshot.id, []),
                )
                for snapshot in snapshots
            ],
            BenchmarkEvidenceInput(
                id=benchmark.id,
                sample_count=benchmark.sample_count,
                confidence=cast(
                    Literal["raw_only", "low_confidence", "normal"],
                    benchmark.confidence,
                ),
                percentiles=percentile_values,
            ),
            comparisons,
        )

    def request(
        self,
        content_id: UUID,
        *,
        trigger_kind: Literal["manual", "auto"] = "manual",
    ) -> tuple[AnalysisRun, bool, bool]:
        content = self._content(content_id, mutation=True)
        bundle = self._bundle(content)
        settings = get_settings()
        model_config_id, binding = resolve_analysis_model_binding(
            session=self.session,
            context=self.context,
            cipher=SecretCipher(
                settings.model_secret_encryption_key.get_secret_value()
            ),
            mock_mode=settings.app_mock_mode,
        )
        context = AnalysisVersionContext(
            workspace_id=content.workspace_id,
            account_id=content.account_id,
            content_id=content.id,
            benchmark_run_id=bundle.benchmark.id,
            snapshot_ids=[snapshot.id for snapshot in bundle.snapshots],
            model_config_id=model_config_id,
            model_provider=binding.provider,
            model_version=binding.model_id,
            provider_contract_version=binding.contract_version,
            model_config_version=(
                binding.configuration_version or "legacy"
            ),
            prompt_version=ANALYSIS_PROMPT_VERSION,
            algorithm_version=ANALYSIS_ALGORITHM_VERSION,
            benchmark_algorithm_version=BENCHMARK_ALGORITHM_VERSION,
            trigger_kind=trigger_kind,
            requested_by=self.context.member_id,
        )
        key = analysis_cache_key(bundle, context)
        existing = self.session.scalar(
            select(AnalysisRun).where(
                AnalysisRun.workspace_id == content.workspace_id,
                AnalysisRun.content_id == content.id,
                AnalysisRun.cache_key == key,
                AnalysisRun.status.in_([
                    AnalysisRunStatus.PENDING,
                    AnalysisRunStatus.RUNNING,
                    AnalysisRunStatus.SUCCEEDED,
                ]),
            ).order_by(AnalysisRun.created_at.desc())
        )
        if existing is not None:
            if existing.benchmark_run_id != bundle.benchmark.id:
                unused_benchmark = self.session.get(BenchmarkRun, bundle.benchmark.id)
                if unused_benchmark is not None:
                    self.session.delete(unused_benchmark)
                    self.session.flush()
            return existing, analysis_run_is_dispatchable(existing), False
        run = AnalysisRun(
            workspace_id=content.workspace_id,
            account_id=content.account_id,
            content_id=content.id,
            benchmark_run_id=bundle.benchmark.id,
            snapshot_ids=[str(snapshot.id) for snapshot in bundle.snapshots],
            status=AnalysisRunStatus.PENDING,
            trigger_kind=trigger_kind,
            cache_key=key,
            evidence_bundle=bundle.model_dump(mode="json"),
            model_version=context.model_version,
            model_config_id=context.model_config_id,
            model_provider=context.model_provider,
            provider_contract_version=context.provider_contract_version,
            model_config_version=context.model_config_version,
            prompt_version=context.prompt_version,
            algorithm_version=context.algorithm_version,
            benchmark_algorithm_version=context.benchmark_algorithm_version,
            requested_by=context.requested_by,
        )
        try:
            with self.session.begin_nested():
                self.session.add(run)
                self.session.flush()
        except IntegrityError:
            existing = self.session.scalar(
                select(AnalysisRun).where(
                    AnalysisRun.content_id == content.id,
                    AnalysisRun.cache_key == key,
                    AnalysisRun.status.in_([
                        AnalysisRunStatus.PENDING,
                        AnalysisRunStatus.RUNNING,
                        AnalysisRunStatus.SUCCEEDED,
                    ]),
                )
            )
            if existing is None:
                raise
            unused_benchmark = self.session.get(BenchmarkRun, bundle.benchmark.id)
            if unused_benchmark is not None:
                self.session.delete(unused_benchmark)
                self.session.flush()
            return existing, analysis_run_is_dispatchable(existing), False
        EventService(self.session, self.context).record(
            ProductEventInput(
                event_name=EventName.ANALYSIS_STARTED,
                idempotency_key=f"analysis-started:{run.id}",
                analysis_run_id=run.id,
                properties={"trigger_kind": trigger_kind},
                provider_mode=(
                    "mock" if run.model_version.startswith("mock") else "real"
                ),
            )
        )
        return run, True, True

    def read(self, content_id: UUID, run_id: UUID) -> AnalysisRun:
        self._content(content_id, mutation=False)
        run = self.session.scalar(
            select(AnalysisRun).where(
                AnalysisRun.id == run_id,
                AnalysisRun.content_id == content_id,
                AnalysisRun.workspace_id == self.context.workspace_id,
            )
        )
        if run is None:
            raise LookupError("analysis run not found")
        return run

    def setting(self, account_id: UUID) -> AccountAnalysisSetting | None:
        self._account(account_id, mutation=False)
        return self.session.scalar(
            select(AccountAnalysisSetting).where(
                AccountAnalysisSetting.account_id == account_id,
                AccountAnalysisSetting.workspace_id == self.context.workspace_id,
            )
        )

    def update_setting(self, account_id: UUID, auto_analyze: bool) -> AccountAnalysisSetting:
        self._account(account_id, mutation=True)
        setting = self.setting(account_id)
        if setting is None:
            setting = AccountAnalysisSetting(
                workspace_id=self.context.workspace_id,
                account_id=account_id,
                auto_analyze=auto_analyze,
            )
            self.session.add(setting)
        else:
            setting.auto_analyze = auto_analyze
        self.session.flush()
        return setting

    def mark_viewed(self, content_id: UUID, run_id: UUID):
        run = self.read(content_id, run_id)
        if run.status != AnalysisRunStatus.SUCCEEDED:
            raise ValueError("only successful analysis can be viewed")
        return EventService(self.session, self.context).record(
            ProductEventInput(
                event_name=EventName.ANALYSIS_VIEWED,
                idempotency_key=(
                    f"analysis-viewed:{run.id}:{self.context.member_id}"
                ),
                analysis_run_id=run.id,
                properties={"analysis_version": run.algorithm_version},
                provider_mode=(
                    "mock" if run.model_version.startswith("mock") else "real"
                ),
            )
        )

    def feedback(
        self,
        content_id: UUID,
        run_id: UUID,
        rating: str,
        *,
        idempotency_key: str | None = None,
    ):
        run = self.read(content_id, run_id)
        require_permission(self.context.role, Permission.WRITE_CONTENT)
        if run.status != AnalysisRunStatus.SUCCEEDED:
            raise ValueError("only successful analysis accepts feedback")
        return EventService(self.session, self.context).record(
            ProductEventInput(
                event_name=EventName.ANALYSIS_FEEDBACK,
                idempotency_key=idempotency_key
                or f"analysis-feedback:{run.id}:{self.context.member_id}:{rating}",
                analysis_run_id=run.id,
                properties={
                    "rating": rating,
                    "analysis_version": run.algorithm_version,
                },
                provider_mode=(
                    "mock" if run.model_version.startswith("mock") else "real"
                ),
            )
        )

    def save_suggestion(
        self,
        content_id: UUID,
        run_id: UUID,
        recommendation_id: str,
    ) -> AnalysisSuggestion:
        run = self.read(content_id, run_id)
        require_permission(self.context.role, Permission.WRITE_CONTENT)
        if run.status != AnalysisRunStatus.SUCCEEDED or run.report is None:
            raise ValueError("analysis report is not available")
        report = AnalysisReport.model_validate(run.report)
        recommendation = next(
            (item for item in report.recommendations if item.id == recommendation_id),
            None,
        )
        if recommendation is None:
            raise LookupError("recommendation not found")
        existing = self.session.scalar(
            select(AnalysisSuggestion).where(
                AnalysisSuggestion.analysis_run_id == run.id,
                AnalysisSuggestion.recommendation_id == recommendation_id,
            )
        )
        if existing is not None:
            return existing
        suggestion = AnalysisSuggestion(
            workspace_id=self.context.workspace_id,
            analysis_run_id=run.id,
            recommendation_id=recommendation_id,
            recommendation=recommendation.model_dump(mode="json"),
            adoption_status="saved",
        )
        self.session.add(suggestion)
        self.session.flush()
        EventService(self.session, self.context).record(
            ProductEventInput(
                event_name=EventName.SUGGESTION_SAVED,
                idempotency_key=f"suggestion-saved:{suggestion.id}",
                suggestion_id=suggestion.id,
                properties={"suggestion_version": run.algorithm_version},
                provider_mode=(
                    "mock" if run.model_version.startswith("mock") else "real"
                ),
            )
        )
        return suggestion

    def adopt_suggestion(
        self,
        content_id: UUID,
        suggestion_id: UUID,
        adoption_status: str,
    ) -> AnalysisSuggestion:
        self._content(content_id, mutation=True)
        suggestion = self.session.scalar(
            select(AnalysisSuggestion)
            .join(AnalysisRun, AnalysisRun.id == AnalysisSuggestion.analysis_run_id)
            .where(
                AnalysisSuggestion.id == suggestion_id,
                AnalysisSuggestion.workspace_id == self.context.workspace_id,
                AnalysisRun.content_id == content_id,
            )
        )
        if suggestion is None:
            raise LookupError("analysis suggestion not found")
        if suggestion.adoption_status == adoption_status:
            return suggestion
        if suggestion.adoption_status != "saved":
            raise ValueError("suggestion adoption status is terminal")
        suggestion.adoption_status = adoption_status
        run = self.session.get(AnalysisRun, suggestion.analysis_run_id)
        assert run is not None
        EventService(self.session, self.context).record(
            ProductEventInput(
                event_name=(
                    EventName.SUGGESTION_ADOPTED
                    if adoption_status == "adopted"
                    else EventName.SUGGESTION_REJECTED
                ),
                idempotency_key=(
                    f"suggestion-{adoption_status}:{suggestion.id}"
                ),
                suggestion_id=suggestion.id,
                properties={"suggestion_version": run.algorithm_version},
                provider_mode=(
                    "mock" if run.model_version.startswith("mock") else "real"
                ),
            )
        )
        self.session.flush()
        return suggestion


def account_auto_analysis_enabled(
    session: Session,
    workspace_id: UUID,
    account_id: UUID,
) -> bool:
    setting = session.scalar(
        select(AccountAnalysisSetting).where(
            AccountAnalysisSetting.workspace_id == workspace_id,
            AccountAnalysisSetting.account_id == account_id,
        )
    )
    return bool(setting and setting.auto_analyze)


def analysis_run_is_dispatchable(run: AnalysisRun) -> bool:
    now = utc_now()
    return (
        run.status == AnalysisRunStatus.PENDING
        and (run.next_attempt_at is None or run.next_attempt_at <= now)
        and (run.lease_expires_at is None or run.lease_expires_at <= now)
    )
