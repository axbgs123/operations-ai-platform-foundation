"""Deterministic, opt-in synthetic data for the public Mock demo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import create_session_factory
from app.core.storage import Storage, get_storage
from app.modules.content.account_models import (
    BenchmarkProfile,
    ColumnCampaign,
    ColumnCampaignKind,
    ObjectiveProfile,
    Platform,
    PlatformAccount,
)
from app.modules.content.models import AssetCategory, Content, ContentAsset, ContentStatus
from app.modules.metrics.models import (
    BenchmarkRun,
    ContentType,
    DataSnapshot,
    MetricAggregation,
    MetricDefinition,
    MetricUnit,
    SnapshotMetricValue,
    SnapshotSource,
)
from app.modules.analysis.models import AnalysisRun, AnalysisRunStatus, AnalysisSuggestion
from app.modules.generation.models import TextGenerationRun  # noqa: F401
from app.modules.models.models import ModelConfig  # noqa: F401
from app.modules.risk_rag.models import (
    RiskAuthorizationStatus, RiskChunk, RiskDocument, RiskDocumentScope,
    RiskDocumentStatus, RiskSourceLevel,
)
from app.modules.style_facts.fact_models import (
    FactConflictStatus, FactItem, FactItemStatus, FactSource, FactSourceKind,
    FactSourceLevel, FactSourceStatus,
)
from app.modules.style_facts.style_models import (
    AccountStyleProfile, StyleProfileStatus, StyleSample,
)
from app.modules.workspace.models import Workspace

DEMO_SEED_VERSION = "synthetic-ai-tech-v1"
DEMO_WORKSPACE_NAME = "AI 内容实验室（合成示例）"
DEMO_WORKSPACE_STATUS = f"demo:{DEMO_SEED_VERSION}"
ASSET_KEY = f"demo/{DEMO_SEED_VERSION}/synthetic-cover.txt"
ASSET_CONTENT = b"Synthetic placeholder asset. No external account, user, or production data.\n"


@dataclass(frozen=True)
class DemoSeedResult:
    seed_version: str
    created: bool


def _content_rows() -> tuple[tuple[Platform, str, str, datetime], ...]:
    return (
        (Platform.DOUYIN, "AI 工具如何减少重复运营", "视频脚本与镜头建议均为合成示例数据。", datetime(2026, 7, 8, 4, 0, tzinfo=UTC)),
        (Platform.DOUYIN, "一周 AI 资讯复盘框架", "合成内容：不关联任何真实账号或平台内容。", datetime(2026, 7, 12, 10, 30, tzinfo=UTC)),
        (Platform.XIAOHONGSHU, "用 AI 整理工作流的三个步骤", "合成笔记：演示已确认数据快照。", datetime(2026, 7, 9, 12, 0, tzinfo=UTC)),
        (Platform.XIAOHONGSHU, "轻量 AI 工具箱的通勤灵感", "合成笔记：Mock 分析不等于生产模型效果。", datetime(2026, 7, 14, 11, 15, tzinfo=UTC)),
    )


def seed_demo(session: Session, storage: Storage | None = None) -> DemoSeedResult:
    """Create the demo once, without touching user workspaces or real metrics."""
    workspace = session.scalar(
        select(Workspace).where(Workspace.status == DEMO_WORKSPACE_STATUS)
    )
    if workspace is not None:
        return DemoSeedResult(seed_version=DEMO_SEED_VERSION, created=False)

    workspace = Workspace(name=DEMO_WORKSPACE_NAME, status=DEMO_WORKSPACE_STATUS)
    session.add(workspace)
    session.flush()

    accounts: dict[Platform, PlatformAccount] = {}
    for platform, name in (
        (Platform.DOUYIN, "合成 AI 科技抖音账号"),
        (Platform.XIAOHONGSHU, "合成 AI 科技小红书账号"),
    ):
        account = PlatformAccount(workspace_id=workspace.id, platform=platform, name=name)
        session.add(account)
        session.flush()
        accounts[platform] = account
        objective = ObjectiveProfile(
            workspace_id=workspace.id,
            account_id=account.id,
            version=1,
            objectives=["知识传播", "内容复盘"],
            metric_weights={"views": 0.5, "likes": 0.3, "comments": 0.2},
        )
        benchmark = BenchmarkProfile(
            workspace_id=workspace.id,
            account_id=account.id,
            version=1,
            sample_size=2,
        )
        session.add_all((objective, benchmark))
        session.flush()
        session.add(
            ColumnCampaign(
                workspace_id=workspace.id,
                account_id=account.id,
                name="合成 AI 内容实验栏目",
                kind=ColumnCampaignKind.COLUMN,
                objective_profile_id=objective.id,
                benchmark_profile_id=benchmark.id,
            )
        )
        for key, label in (("views", "展示"), ("likes", "喜欢"), ("comments", "评论")):
            session.add(
                MetricDefinition(
                    workspace_id=workspace.id,
                    platform=platform,
                    content_type=ContentType.VIDEO if platform is Platform.DOUYIN else ContentType.IMAGE_TEXT,
                    key=key,
                    label=label,
                    unit=MetricUnit.COUNT,
                    aggregation=MetricAggregation.LATEST,
                    higher_is_better=True,
                    is_default=True,
                )
            )

    session.flush()
    definitions = {
        (definition.platform, definition.key): definition
        for definition in session.scalars(select(MetricDefinition).where(MetricDefinition.workspace_id == workspace.id))
    }
    seeded_contents: list[Content] = []
    seeded_snapshots: list[DataSnapshot] = []
    for index, (platform, title, body, published_at) in enumerate(_content_rows(), start=1):
        account = accounts[platform]
        content_objective = session.scalar(
            select(ObjectiveProfile).where(ObjectiveProfile.account_id == account.id)
        )
        content_benchmark = session.scalar(
            select(BenchmarkProfile).where(BenchmarkProfile.account_id == account.id)
        )
        assert content_objective is not None and content_benchmark is not None
        content = Content(
            workspace_id=workspace.id,
            account_id=account.id,
            platform=platform,
            title=title,
            body=f"[synthetic:{DEMO_SEED_VERSION}] {body}",
            objective_profile_id=content_objective.id,
            benchmark_profile_id=content_benchmark.id,
            content_type=ContentType.VIDEO if platform is Platform.DOUYIN else ContentType.IMAGE_TEXT,
            status=ContentStatus.PUBLISHED,
            published_title=title,
            published_body=body,
            published_at=published_at,
        )
        session.add(content)
        session.flush()
        seeded_contents.append(content)
        snapshot = DataSnapshot(
            workspace_id=workspace.id,
            content_id=content.id,
            account_id=account.id,
            platform=platform,
            content_type=content.content_type,
            collected_at=published_at,
            age_seconds=86_400,
            maturity_bucket="D1",
            source=SnapshotSource.MANUAL,
            confirmed=True,
            analytics_eligible=False,
            confirmed_at=published_at,
        )
        session.add(snapshot)
        session.flush()
        seeded_snapshots.append(snapshot)
        for key, value in (("views", 1000 * index), ("likes", 100 * index), ("comments", 10 * index)):
            session.add(
                SnapshotMetricValue(
                    workspace_id=workspace.id,
                    snapshot_id=snapshot.id,
                    metric_key=key,
                    raw_value=Decimal(value),
                    normalized_value=Decimal(value),
                    eligible_for_benchmark=False,
                    metric_definition_id=definitions[(platform, key)].id,
                )
            )

    first_content = seeded_contents[0]
    first_snapshot = seeded_snapshots[0]
    first_account = accounts[Platform.DOUYIN]
    session.add(
        ContentAsset(
            workspace_id=workspace.id, content_id=first_content.id, category=AssetCategory.COVER,
            object_key=ASSET_KEY, file_name="synthetic-cover.txt", mime_type="text/plain", size=len(ASSET_CONTENT),
        )
    )
    first_objective = session.scalar(select(ObjectiveProfile).where(ObjectiveProfile.account_id == first_account.id))
    first_benchmark_profile = session.scalar(
        select(BenchmarkProfile).where(BenchmarkProfile.account_id == first_account.id)
    )
    assert first_objective is not None and first_benchmark_profile is not None
    draft = Content(
        workspace_id=workspace.id, account_id=first_account.id, platform=Platform.DOUYIN,
        title="Mock 生成草稿：AI 复盘清单", body=f"[synthetic:{DEMO_SEED_VERSION}] Mock 生成草稿，不等于生产模型效果。",
        objective_profile_id=first_objective.id, benchmark_profile_id=first_benchmark_profile.id,
        content_type=ContentType.VIDEO, status=ContentStatus.DRAFT,
    )
    session.add(draft)
    session.add(StyleSample(workspace_id=workspace.id, account_id=first_account.id, scope_key="default", content_id=first_content.id))
    session.add(AccountStyleProfile(
        workspace_id=workspace.id, account_id=first_account.id, scope_key="default", version=1,
        status=StyleProfileStatus.CONFIRMED, style={"tone": "清晰、克制、合成示例"},
        sample_content_ids=[str(first_content.id)], diff={}, confirmed_at=first_content.published_at,
    ))
    fact_source = FactSource(
        workspace_id=workspace.id, kind=FactSourceKind.TEXT, level=FactSourceLevel.L1,
        title="合成 AI 科技事实样本", status=FactSourceStatus.PARSED,
        source_text="此条目为合成示例，未经外部抓取。", untrusted_data=False,
    )
    session.add(fact_source)
    session.flush()
    session.add(FactItem(
        workspace_id=workspace.id, source_id=fact_source.id, field_name="示例边界", field_code="demo_boundary",
        value="Mock 数据仅用于产品演示", source_location="合成文本第 1 行", confidence=1.0,
        status=FactItemStatus.CONFIRMED, conflict_status=FactConflictStatus.CLEAR, confirmed_at=first_content.published_at,
    ))
    risk_document = RiskDocument(
        workspace_id=workspace.id, platform=Platform.DOUYIN, scope=RiskDocumentScope.PRIVATE,
        source_level=RiskSourceLevel.S1, title="合成风控规则：避免绝对化承诺",
        authorization_status=RiskAuthorizationStatus.NOT_REQUIRED, status=RiskDocumentStatus.ACTIVE,
        version=1, private_document_id="synthetic-demo-risk-v1", effective_at=first_content.published_at,
        untrusted_data=False, redistribution_authorized=False,
    )
    session.add(risk_document)
    session.flush()
    session.add(RiskChunk(
        workspace_id=workspace.id, document_id=risk_document.id, platform=Platform.DOUYIN,
        scope=RiskDocumentScope.PRIVATE, chunk_index=0, source_location="synthetic:1",
        text="合成规则：Mock 演示不得承诺真实生产效果。", metadata_json={"synthetic": True},
    ))
    benchmark_run = BenchmarkRun(
        workspace_id=workspace.id, account_id=first_account.id, platform=Platform.DOUYIN,
        content_type=ContentType.VIDEO, maturity_bucket="D1", range_settings={"kind": "latest_n", "n": 2},
        sample_snapshot_ids=[str(item.id) for item in seeded_snapshots[:2]], sample_count=2,
        percentile_values={"views": {"median": "1500"}}, weights={"views": "0.5"},
        confidence="raw_only", algorithm_version="synthetic-demo-v1",
    )
    session.add(benchmark_run)
    session.flush()
    analysis = AnalysisRun(
        workspace_id=workspace.id, account_id=first_account.id, content_id=first_content.id,
        benchmark_run_id=benchmark_run.id, snapshot_ids=[str(first_snapshot.id)], status=AnalysisRunStatus.SUCCEEDED,
        trigger_kind="mock", cache_key="synthetic-demo-analysis-v1", evidence_bundle={"synthetic": True},
        model_version="mock-v1", prompt_version="synthetic-v1", algorithm_version="synthetic-v1",
        benchmark_algorithm_version="synthetic-demo-v1", report={"summary": "Mock 分析：内容结构清晰。"}, completed_at=first_content.published_at,
    )
    session.add(analysis)
    session.flush()
    session.add(AnalysisSuggestion(
        workspace_id=workspace.id, analysis_run_id=analysis.id, recommendation_id="synthetic-hook",
        recommendation={"text": "建议：用具体问题开启合成示例内容。", "synthetic": True},
    ))
    if storage is not None:
        storage.put_object(ASSET_KEY, ASSET_CONTENT, mime_type="text/plain")
    return DemoSeedResult(seed_version=DEMO_SEED_VERSION, created=True)


def main() -> int:
    settings = get_settings()
    if not settings.demo_seed_enabled:
        raise SystemExit("DEMO_SEED_ENABLED=true is required for demo seeding")
    with create_session_factory()() as session:
        result = seed_demo(session, get_storage())
        session.commit()
    print(f"demo seed {result.seed_version}: {'created' if result.created else 'already present'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
