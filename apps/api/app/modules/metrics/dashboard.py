from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.content.account_models import (
    BenchmarkProfile,
    ObjectiveProfile,
    PlatformAccount,
)
from app.modules.content.models import Content
from app.modules.metrics.benchmark import (
    confidence_band,
    historical_percentile,
    percentile,
)
from app.modules.metrics.definitions import get_metric_definitions
from app.modules.metrics.maturity import MaturityBucket
from app.modules.metrics.models import (
    ContentType,
    DataSnapshot,
    MetricDefinition,
    SnapshotMetricValue,
)
from app.modules.workspace.permissions import Permission, require_permission


class DrillDownFilter(BaseModel):
    workspace_id: UUID
    account_id: UUID
    platform: Literal["douyin", "xiaohongshu"]
    content_type: Literal["video", "image_text"]
    maturity_bucket: Literal["1h", "24h", "72h", "7d"]
    metric_key: str | None = None
    required_metric_keys: list[str] = Field(default_factory=list)
    attention: Literal["candidate", "anomaly"] | None = None


class GoalMetricCard(BaseModel):
    metric_key: str
    label: str
    unit: Literal["count", "ratio", "seconds", "number"]
    current_value: float | None
    change_rate: float | None
    historical_percentile: float | None
    data_completeness: float
    sample_count: int
    confidence: Literal["raw_only", "low_confidence", "normal"]
    explanation: str
    drill_down_filter: DrillDownFilter


class DashboardChartPoint(BaseModel):
    x: str
    y: float
    value: float | None = None
    content_id: UUID | None = None


class DashboardChart(BaseModel):
    id: str
    kind: Literal["line", "funnel", "heatmap"]
    title: str
    metric_key: str | None
    unit: Literal["count", "ratio", "seconds", "number"]
    sample_count: int
    explanation: str
    points: list[DashboardChartPoint]
    drill_down_filter: DrillDownFilter


class DashboardAttentionItem(BaseModel):
    content_id: UUID
    title: str
    kind: Literal["candidate", "anomaly"]
    reason: str
    drill_down_filter: DrillDownFilter


class DashboardBenchmarkBand(BaseModel):
    metric_key: str
    label: str
    unit: Literal["count", "ratio", "seconds", "number"]
    sample_count: int
    median: float
    top_25: float
    top_10: float


class DashboardChartGate(BaseModel):
    kind: Literal["line", "funnel", "heatmap"]
    eligible: bool
    reason: str
    actual_sample_count: int
    required_sample_count: int
    missing_metric_keys: list[str] = Field(default_factory=list)


class DashboardContentItem(BaseModel):
    content_id: UUID
    title: str
    account_name: str
    status: str


class AccountDashboard(BaseModel):
    account_id: UUID
    account_name: str
    platform: Literal["douyin", "xiaohongshu"]
    content_type: Literal["video", "image_text"]
    maturity_bucket: Literal["1h", "24h", "72h", "7d"]
    sample_count: int
    data_completeness: float = Field(ge=0, le=1)
    benchmark_sample_size: int
    confidence: Literal["raw_only", "low_confidence", "normal"]
    explanation: str
    goal_cards: list[GoalMetricCard]
    benchmark_bands: list[DashboardBenchmarkBand]
    charts: list[DashboardChart]
    chart_gates: list[DashboardChartGate]
    attention_items: list[DashboardAttentionItem]
    next_actions: list[str]


@dataclass(frozen=True)
class SnapshotSample:
    snapshot: DataSnapshot
    content: Content
    values: dict[str, Decimal]


class DashboardService:
    def __init__(self, session: Session, context: WorkspaceContext) -> None:
        self._session = session
        self._context = context

    def _account(self, account_id: UUID) -> PlatformAccount:
        account = self._session.scalar(
            select(PlatformAccount).where(
                PlatformAccount.id == account_id,
                PlatformAccount.workspace_id == self._context.workspace_id,
            )
        )
        if account is None:
            raise LookupError("account not found")
        return account

    def _configuration(
        self, account_id: UUID
    ) -> tuple[ObjectiveProfile, BenchmarkProfile]:
        objective = self._session.scalar(
            select(ObjectiveProfile)
            .where(
                ObjectiveProfile.account_id == account_id,
                ObjectiveProfile.is_account_default.is_(True),
            )
            .order_by(ObjectiveProfile.version.desc())
            .limit(1)
        )
        benchmark = self._session.scalar(
            select(BenchmarkProfile)
            .where(
                BenchmarkProfile.account_id == account_id,
                BenchmarkProfile.is_account_default.is_(True),
            )
            .order_by(BenchmarkProfile.version.desc())
            .limit(1)
        )
        if objective is None or benchmark is None:
            raise LookupError("account configuration not found")
        return objective, benchmark

    def _samples(
        self,
        account: PlatformAccount,
        content_type: ContentType,
        maturity_bucket: MaturityBucket,
        limit: int,
    ) -> list[SnapshotSample]:
        ranked_snapshots = (
            select(
                DataSnapshot.id.label("snapshot_id"),
                func.row_number().over(
                    partition_by=DataSnapshot.content_id,
                    order_by=(
                        DataSnapshot.collected_at.desc(),
                        DataSnapshot.id.desc(),
                    ),
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
                .join(
                    ranked_snapshots,
                    ranked_snapshots.c.snapshot_id == DataSnapshot.id,
                )
                .where(
                    ranked_snapshots.c.snapshot_rank == 1,
                    Content.workspace_id == self._context.workspace_id,
                    Content.account_id == account.id,
                    Content.platform == account.platform,
                    Content.content_type == content_type,
                    Content.deleted_at.is_(None),
                )
                .order_by(
                    Content.published_at.desc(),
                    DataSnapshot.collected_at.desc(),
                    DataSnapshot.id.desc(),
                )
                .limit(limit)
            )
        )
        snapshot_ids = [snapshot.id for snapshot, _ in latest]
        values_by_snapshot: dict[UUID, dict[str, Decimal]] = {
            snapshot_id: {} for snapshot_id in snapshot_ids
        }
        if snapshot_ids:
            values = self._session.execute(
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
            for snapshot_id, metric_key, value in values:
                if value is not None:
                    values_by_snapshot[snapshot_id][metric_key] = value
        return [
            SnapshotSample(snapshot, content, values_by_snapshot[snapshot.id])
            for snapshot, content in latest
        ]

    def _definitions(
        self,
        account: PlatformAccount,
        content_type: ContentType,
    ) -> dict:
        available = list(get_metric_definitions(account.platform, content_type))
        available.extend(
            self._session.scalars(
                select(MetricDefinition).where(
                    MetricDefinition.workspace_id == self._context.workspace_id,
                    MetricDefinition.platform == account.platform,
                    MetricDefinition.content_type == content_type,
                )
            )
        )
        return {definition.key: definition for definition in available}

    @staticmethod
    def _metric_keys(
        objective: ObjectiveProfile,
        definitions: dict,
    ) -> list[str]:
        available = list(definitions.values())
        available_keys = set(definitions)
        keys = [key for key in objective.metric_weights if key in available_keys]
        for definition in available:
            if definition.key not in keys:
                keys.append(definition.key)
            if len(keys) == 4:
                break
        return keys[:6]

    @staticmethod
    def _charts(
        samples: list[SnapshotSample],
        definitions: dict,
        metric_key: str,
        base_filter: Mapping[str, object],
    ) -> list[DashboardChart]:
        definition = definitions[metric_key]
        chronological = sorted(
            samples,
            key=lambda sample: sample.snapshot.collected_at,
        )
        trend_points = [
            DashboardChartPoint(
                x=sample.snapshot.collected_at.isoformat(),
                y=float(sample.values[metric_key]),
                content_id=sample.content.id,
            )
            for sample in chronological
            if metric_key in sample.values
        ]
        charts: list[DashboardChart] = []
        if len(trend_points) >= 2:
            charts.append(
                DashboardChart(
                    id=f"trend-{metric_key}",
                    kind="line",
                    title=f"账号{definition.label}表现趋势",
                    metric_key=metric_key,
                    unit=definition.unit.value,
                    sample_count=len(trend_points),
                    explanation=(
                        "按每条内容最新一条同口径快照排列；"
                        f"有效内容样本 {len(trend_points)} 条。"
                    ),
                    points=trend_points,
                    drill_down_filter=DrillDownFilter.model_validate(
                        {**base_filter, "metric_key": metric_key}
                    ),
                )
            )

        if "impressions" in definitions and "views" in definitions:
            paired = [
                sample
                for sample in samples
                if "impressions" in sample.values and "views" in sample.values
            ]
            if len(paired) >= 5:
                impressions = [sample.values["impressions"] for sample in paired]
                views = [sample.values["views"] for sample in paired]
                charts.append(
                    DashboardChart(
                        id="funnel-impressions-views",
                        kind="funnel",
                        title="曝光到阅读/播放",
                        metric_key=None,
                        unit="count",
                        sample_count=len(paired),
                        explanation=(
                            f"同一内容同时具备两阶段指标的样本 {len(paired)} 条。"
                        ),
                        points=[
                            DashboardChartPoint(
                                x="曝光量", y=float(sum(impressions))
                            ),
                            DashboardChartPoint(
                                x="阅读/播放量", y=float(sum(views))
                            ),
                        ],
                        drill_down_filter=DrillDownFilter.model_validate(
                            {
                                **base_filter,
                                "required_metric_keys": ["impressions", "views"],
                            }
                        ),
                    )
                )

        publication_samples = [
            (sample, published_at)
            for sample in samples
            if (published_at := sample.content.published_at) is not None
            and metric_key in sample.values
        ]
        if len(publication_samples) >= 10:
            charts.append(
                DashboardChart(
                    id=f"publication-heatmap-{metric_key}",
                    kind="heatmap",
                    title=f"发布时间与{definition.label}",
                    metric_key=metric_key,
                    unit=definition.unit.value,
                    sample_count=len(publication_samples),
                    explanation=(
                        f"具备发布时间的有效样本 {len(publication_samples)} 条。"
                    ),
                    points=[
                        DashboardChartPoint(
                            x=f"{published_at.hour:02d}:00",
                            y=float(published_at.weekday()),
                            value=float(sample.values[metric_key]),
                            content_id=sample.content.id,
                        )
                        for sample, published_at in publication_samples
                    ],
                    drill_down_filter=DrillDownFilter.model_validate(
                        {**base_filter, "metric_key": metric_key}
                    ),
                )
            )
        return charts

    @staticmethod
    def _benchmark_bands(
        samples: list[SnapshotSample],
        definitions: dict,
        metric_keys: list[str],
    ) -> list[DashboardBenchmarkBand]:
        bands: list[DashboardBenchmarkBand] = []
        for metric_key in metric_keys:
            definition = definitions[metric_key]
            values = [
                sample.values[metric_key]
                for sample in samples
                if metric_key in sample.values
            ]
            if len(values) < 5:
                continue
            top_25_quantile = 0.75 if definition.higher_is_better else 0.25
            top_10_quantile = 0.9 if definition.higher_is_better else 0.1
            bands.append(
                DashboardBenchmarkBand(
                    metric_key=metric_key,
                    label=definition.label,
                    unit=definition.unit.value,
                    sample_count=len(values),
                    median=float(percentile(values, 0.5)),
                    top_25=float(percentile(values, top_25_quantile)),
                    top_10=float(percentile(values, top_10_quantile)),
                )
            )
        return bands

    @staticmethod
    def _chart_gates(
        samples: list[SnapshotSample],
        definitions: dict,
        metric_key: str,
    ) -> list[DashboardChartGate]:
        trend_count = sum(metric_key in sample.values for sample in samples)
        trend_eligible = trend_count >= 2
        line = DashboardChartGate(
            kind="line",
            eligible=trend_eligible,
            reason=(
                "同口径有效快照满足趋势展示条件。"
                if trend_eligible
                else (
                    "趋势图至少需要 2 条同口径有效快照；"
                    f"当前 {trend_count} 条。"
                )
            ),
            actual_sample_count=trend_count,
            required_sample_count=2,
        )

        required_funnel_keys = ["impressions", "views"]
        missing_funnel_keys = [
            key for key in required_funnel_keys if key not in definitions
        ]
        funnel_count = (
            0
            if missing_funnel_keys
            else sum(
                all(key in sample.values for key in required_funnel_keys)
                for sample in samples
            )
        )
        funnel_eligible = not missing_funnel_keys and funnel_count >= 5
        if missing_funnel_keys:
            funnel_reason = (
                "当前平台或内容类型不提供漏斗必要字段："
                + "、".join(missing_funnel_keys)
                + "。"
            )
        elif funnel_eligible:
            funnel_reason = "漏斗必要字段完整且同口径样本满足展示条件。"
        else:
            funnel_reason = (
                "漏斗至少需要 5 条同时包含曝光和阅读/播放的快照；"
                f"当前 {funnel_count} 条。"
            )
        funnel = DashboardChartGate(
            kind="funnel",
            eligible=funnel_eligible,
            reason=funnel_reason,
            actual_sample_count=funnel_count,
            required_sample_count=5,
            missing_metric_keys=missing_funnel_keys,
        )

        publication_count = sum(
            sample.content.published_at is not None
            and metric_key in sample.values
            for sample in samples
        )
        heatmap_eligible = publication_count >= 10
        heatmap = DashboardChartGate(
            kind="heatmap",
            eligible=heatmap_eligible,
            reason=(
                "发布时间样本满足热力图展示条件。"
                if heatmap_eligible
                else (
                    "发布时间热力图至少需要 10 条带发布时间的有效样本；"
                    f"当前 {publication_count} 条。"
                )
            ),
            actual_sample_count=publication_count,
            required_sample_count=10,
        )
        return [line, funnel, heatmap]

    @staticmethod
    def _attention_pair(
        valued: list[SnapshotSample],
        metric_key: str,
        higher_is_better: bool,
    ) -> tuple[SnapshotSample, SnapshotSample]:
        maximum = max(valued, key=lambda sample: sample.values[metric_key])
        minimum = min(valued, key=lambda sample: sample.values[metric_key])
        return (
            (maximum, minimum) if higher_is_better else (minimum, maximum)
        )

    @staticmethod
    def _attention_items(
        samples: list[SnapshotSample],
        metric_key: str,
        metric_label: str,
        higher_is_better: bool,
        base_filter: Mapping[str, object],
    ) -> list[DashboardAttentionItem]:
        valued = [sample for sample in samples if metric_key in sample.values]
        if len(valued) < 10:
            return []
        values = [sample.values[metric_key] for sample in valued]
        high, low = DashboardService._attention_pair(
            valued, metric_key, higher_is_better
        )
        high_quantile = 0.9 if higher_is_better else 0.1
        low_quantile = 0.25 if higher_is_better else 0.75
        high_threshold = percentile(values, high_quantile)
        low_threshold = percentile(values, low_quantile)
        return [
            DashboardAttentionItem(
                content_id=high.content.id,
                title=high.content.title,
                kind="candidate",
                reason=(
                    f"{metric_label}进入样本表现较优区间"
                    f"（P{int(high_quantile * 100)} 参考值 "
                    f"{float(high_threshold):g}）。"
                ),
                drill_down_filter=DrillDownFilter.model_validate(
                    {
                        **base_filter,
                        "metric_key": metric_key,
                        "attention": "candidate",
                    }
                ),
            ),
            DashboardAttentionItem(
                content_id=low.content.id,
                title=low.content.title,
                kind="anomaly",
                reason=(
                    f"{metric_label}进入样本表现较弱区间"
                    f"（P{int(low_quantile * 100)} 参考值 "
                    f"{float(low_threshold):g}）。"
                ),
                drill_down_filter=DrillDownFilter.model_validate(
                    {
                        **base_filter,
                        "metric_key": metric_key,
                        "attention": "anomaly",
                    }
                ),
            ),
        ]

    def build(
        self,
        account_id: UUID,
        *,
        content_type: ContentType,
        maturity_bucket: MaturityBucket,
    ) -> AccountDashboard:
        require_permission(self._context.role, Permission.READ_CONTENT)
        account = self._account(account_id)
        objective, benchmark = self._configuration(account.id)
        samples = self._samples(
            account,
            content_type,
            maturity_bucket,
            benchmark.sample_size,
        )
        sample_count = len(samples)
        confidence = confidence_band(sample_count)
        definitions = self._definitions(account, content_type)
        base_filter = {
            "workspace_id": self._context.workspace_id,
            "account_id": account.id,
            "platform": account.platform.value,
            "content_type": content_type.value,
            "maturity_bucket": maturity_bucket.value,
        }
        cards: list[GoalMetricCard] = []
        for metric_key in self._metric_keys(objective, definitions):
            definition = definitions[metric_key]
            history = [
                sample.values[metric_key]
                for sample in samples
                if metric_key in sample.values
            ]
            current = history[0] if history else None
            previous = history[1] if len(history) > 1 else None
            change = (
                (current - previous) / previous
                if current is not None and previous not in (None, Decimal(0))
                else None
            )
            percentile = (
                historical_percentile(
                    current,
                    history,
                    higher_is_better=definition.higher_is_better,
                )
                if current is not None and len(history) >= 5
                else None
            )
            cards.append(
                GoalMetricCard(
                    metric_key=metric_key,
                    label=definition.label,
                    unit=definition.unit.value,
                    current_value=float(current) if current is not None else None,
                    change_rate=float(change) if change is not None else None,
                    historical_percentile=(
                        float(percentile) if percentile is not None else None
                    ),
                    data_completeness=(
                        len(history) / sample_count if sample_count else 0
                    ),
                    sample_count=len(history),
                    confidence=confidence_band(len(history)).value,
                    explanation=(
                        f"该指标有效样本 {len(history)} 条，"
                        f"置信度为 {confidence_band(len(history)).value}。"
                    ),
                    drill_down_filter=DrillDownFilter.model_validate(
                        {**base_filter, "metric_key": metric_key}
                    ),
                )
            )
        if sample_count < 5:
            explanation = (
                f"实际样本 {sample_count} 条，少于 5 条，仅展示原始指标卡。"
            )
        elif sample_count < 10:
            explanation = (
                f"实际样本 {sample_count} 条，当前为低置信度结果，请结合原始内容判断。"
            )
        else:
            explanation = f"实际样本 {sample_count} 条，已按同平台、账号、内容类型和成熟度比较。"
        actions = (
            ["继续采集同成熟度快照，累计至少 5 条后再展示趋势图。"]
            if sample_count < 5
            else [
                "查看候选与异常内容的共同特征。",
                "记录一个可验证变量，作为下一次内容实验。",
            ]
        )
        primary_metric_key = cards[0].metric_key
        metric_keys = [card.metric_key for card in cards]
        return AccountDashboard(
            account_id=account.id,
            account_name=account.name,
            platform=account.platform.value,
            content_type=content_type.value,
            maturity_bucket=maturity_bucket.value,
            sample_count=sample_count,
            data_completeness=round(
                sum(card.data_completeness for card in cards) / len(cards),
                6,
            ),
            benchmark_sample_size=benchmark.sample_size,
            confidence=confidence.value,
            explanation=explanation,
            goal_cards=cards,
            benchmark_bands=self._benchmark_bands(
                samples,
                definitions,
                metric_keys,
            ),
            charts=self._charts(
                samples,
                definitions,
                primary_metric_key,
                base_filter,
            ),
            chart_gates=self._chart_gates(
                samples,
                definitions,
                primary_metric_key,
            ),
            attention_items=self._attention_items(
                samples,
                primary_metric_key,
                definitions[primary_metric_key].label,
                definitions[primary_metric_key].higher_is_better,
                base_filter,
            ),
            next_actions=actions,
        )

    def drill_down(
        self,
        account_id: UUID,
        *,
        content_type: ContentType,
        maturity_bucket: MaturityBucket,
        metric_key: str | None,
        required_metric_keys: list[str],
        attention: Literal["candidate", "anomaly"] | None,
    ) -> list[DashboardContentItem]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        account = self._account(account_id)
        _, benchmark = self._configuration(account.id)
        samples = self._samples(
            account, content_type, maturity_bucket, benchmark.sample_size
        )
        definitions = self._definitions(account, content_type)
        requested_keys = [*required_metric_keys]
        if metric_key is not None:
            requested_keys.append(metric_key)
        if any(key not in definitions for key in requested_keys):
            raise ValueError("metric not compatible with dashboard scope")
        if requested_keys:
            samples = [
                sample
                for sample in samples
                if all(key in sample.values for key in requested_keys)
            ]
        if attention is not None:
            if metric_key is None or len(samples) < 10:
                return []
            higher_is_better = definitions[metric_key].higher_is_better
            candidate, anomaly = self._attention_pair(
                samples, metric_key, higher_is_better
            )
            samples = [candidate if attention == "candidate" else anomaly]
        return [
            DashboardContentItem(
                content_id=sample.content.id,
                title=sample.content.title,
                account_name=account.name,
                status=sample.content.status.value,
            )
            for sample in samples
        ]
