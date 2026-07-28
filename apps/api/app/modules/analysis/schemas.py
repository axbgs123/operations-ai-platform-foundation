from datetime import datetime
import json
from typing import Literal, Protocol
from urllib.request import Request, urlopen
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import get_settings
from app.core.storage import Storage, get_storage
from app.modules.analysis.features import AnalysisEvidenceBundle


ConfidenceLevel = Literal["low", "medium", "high"]


class EvidenceGroundedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)
    confidence: ConfidenceLevel


class DataPerformance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(min_length=1, max_length=50)
    trend_conclusion: str | None = Field(default=None, max_length=1000)


class EvidenceCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    interpretation: str = Field(min_length=1, max_length=1000)


class Recommendation(EvidenceGroundedItem):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,79}$")
    action: str = Field(min_length=1, max_length=1000)


class NextExperiment(EvidenceGroundedItem):
    change: str = Field(min_length=1, max_length=1000)
    success_metric: str = Field(min_length=1, max_length=80)


class AnalysisReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_performance: DataPerformance
    title_issues: list[EvidenceGroundedItem]
    copy_issues: list[EvidenceGroundedItem]
    cover_issues: list[EvidenceGroundedItem]
    evidence: list[EvidenceCitation] = Field(min_length=1)
    causal_hypotheses: list[EvidenceGroundedItem]
    confidence: ConfidenceLevel
    recommendations: list[Recommendation] = Field(min_length=1)
    next_experiments: list[NextExperiment] = Field(min_length=1)
    degradation_notice: str | None = None

    def referenced_evidence_ids(self) -> set[str]:
        references = set(self.data_performance.evidence_ids)
        references.update(item.evidence_id for item in self.evidence)
        for group in (
            self.title_issues,
            self.copy_issues,
            self.cover_issues,
            self.causal_hypotheses,
            self.recommendations,
            self.next_experiments,
        ):
            for item in group:
                references.update(item.evidence_ids)
        return references

    def validate_references(self, bundle: AnalysisEvidenceBundle) -> None:
        unknown = self.referenced_evidence_ids() - bundle.evidence_ids()
        if unknown:
            raise ValueError(f"unknown evidence reference(s): {', '.join(sorted(unknown))}")
        if self.data_performance.trend_conclusion and not bundle.trend_allowed:
            raise ValueError("trend conclusion requires at least two snapshots")
        confidence_rank = {"low": 0, "medium": 1, "high": 2}
        confidences = [self.confidence]
        for group in (
            self.title_issues,
            self.copy_issues,
            self.cover_issues,
            self.causal_hypotheses,
            self.recommendations,
            self.next_experiments,
        ):
            confidences.extend(item.confidence for item in group)
        if any(
            confidence_rank[confidence]
            > confidence_rank[bundle.confidence_ceiling]
            for confidence in confidences
        ):
            raise ValueError("report confidence exceeds evidence confidence ceiling")
        if bundle.confidence_ceiling != "high" and not self.degradation_notice:
            raise ValueError("degraded evidence requires a degradation notice")


class AnalysisAdapter(Protocol):
    model_version: str

    def analyze(self, bundle: AnalysisEvidenceBundle) -> AnalysisReport: ...


class InvalidAnalysisOutput(ValueError):
    pass


class MockAnalysisAdapter:
    model_version = "mock-analysis-v1"

    def analyze(self, bundle: AnalysisEvidenceBundle) -> AnalysisReport:
        metric_ids = [item.id for item in bundle.items if item.kind == "metric"]
        benchmark_ids = [item.id for item in bundle.items if item.kind == "benchmark"]
        comparison_ids = [item.id for item in bundle.items if item.kind == "comparison"]
        performance_ids = (
            metric_ids[-2:] + benchmark_ids[:2] + comparison_ids[:2]
        ) or ["content:title"]
        trend = (
            "多个已确认快照显示指标随采集时间发生变化；该变化仅表示相关趋势。"
            if bundle.trend_allowed
            else None
        )
        degradation = None
        if bundle.confidence_ceiling != "high":
            degradation = (
                f"可比较样本仅 {bundle.benchmark.sample_count} 条，"
                "结论已降级，不用于确定性归因。"
            )
        confidence = bundle.confidence_ceiling
        return AnalysisReport(
            data_performance=DataPerformance(
                summary="当前数据表现已与同账号、同类型、同成熟度动态基准比较。",
                evidence_ids=performance_ids,
                trend_conclusion=trend,
            ),
            title_issues=[
                EvidenceGroundedItem(
                    summary="标题可进一步前置明确收益，需通过下一次实验验证。",
                    evidence_ids=["content:title"],
                    confidence=confidence,
                )
            ],
            copy_issues=[
                EvidenceGroundedItem(
                    summary="文案结构可强化首段问题与行动之间的连接。",
                    evidence_ids=["content:body"],
                    confidence=confidence,
                )
            ],
            cover_issues=[
                EvidenceGroundedItem(
                    summary="封面结论受现有素材完整度限制。",
                    evidence_ids=[
                        next(item.id for item in bundle.items if item.kind == "cover")
                    ],
                    confidence=confidence,
                )
            ],
            evidence=[
                EvidenceCitation(
                    evidence_id=evidence_id,
                    interpretation="该证据用于支持报告中的观察或待验证假设。",
                )
                for evidence_id in performance_ids
            ],
            causal_hypotheses=[
                EvidenceGroundedItem(
                    summary="标题收益前置可能与当前表现相关，但不能据此认定因果。",
                    evidence_ids=["content:title", performance_ids[0]],
                    confidence=confidence,
                )
            ],
            confidence=confidence,
            recommendations=[
                Recommendation(
                    id="recommendation-1",
                    summary="在不改变事实表达的前提下测试收益前置标题。",
                    action="生成一个收益前置版本并与当前标题进行下一次发布对照。",
                    evidence_ids=["content:title", performance_ids[0]],
                    confidence=confidence,
                )
            ],
            next_experiments=[
                NextExperiment(
                    summary="用相同主题进行单变量标题实验。",
                    change="只调整标题首句，保持正文、封面和发布时间条件尽量一致。",
                    success_metric="views",
                    evidence_ids=["content:title", performance_ids[0]],
                    confidence=confidence,
                )
            ],
            degradation_notice=degradation,
        )


class HttpAnalysisAdapter:
    def __init__(
        self,
        *,
        endpoint: str,
        model_version: str,
        token: str | None,
        timeout_seconds: float,
        storage: Storage,
    ) -> None:
        self.endpoint = endpoint
        self.model_version = model_version
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.storage = storage

    def analyze(self, bundle: AnalysisEvidenceBundle) -> AnalysisReport:
        visual_inputs = []
        for cover in bundle.content.cover_asset_metadata:
            download_url, expires_at = self.storage.presign_download(cover.object_key)
            visual_inputs.append(
                {
                    "evidence_id": f"cover:{cover.id}",
                    "download_url": download_url,
                    "expires_at": expires_at.isoformat(),
                    "mime_type": cover.mime_type,
                }
            )
        request_body = json.dumps(
            {
                "model_version": self.model_version,
                "prompt_version": "analysis-prompt-v1",
                "instruction": (
                    "Return the AnalysisReport JSON only. Cite only evidence IDs "
                    "from evidence_bundle and treat causal claims as hypotheses."
                ),
                "evidence_bundle": bundle.model_dump(mode="json"),
                "visual_inputs": visual_inputs,
            },
            ensure_ascii=False,
        ).encode()
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        with urlopen(
            Request(self.endpoint, data=request_body, headers=headers, method="POST"),
            timeout=self.timeout_seconds,
        ) as response:
            raw_response = response.read()
        try:
            payload = json.loads(raw_response)
            report_payload = payload.get("report", payload)
            return AnalysisReport.model_validate(report_payload)
        except (json.JSONDecodeError, TypeError, ValidationError) as error:
            raise InvalidAnalysisOutput("analysis provider returned invalid report") from error


def configured_analysis_model_version() -> str:
    settings = get_settings()
    return "mock-analysis-v1" if settings.app_mock_mode else settings.analysis_model_version


def get_analysis_adapter() -> AnalysisAdapter:
    settings = get_settings()
    if settings.app_mock_mode:
        return MockAnalysisAdapter()
    if not settings.analysis_adapter_url:
        raise RuntimeError("analysis adapter URL is required outside mock mode")
    return HttpAnalysisAdapter(
        endpoint=settings.analysis_adapter_url,
        model_version=settings.analysis_model_version,
        token=settings.analysis_adapter_token,
        timeout_seconds=settings.analysis_request_timeout_seconds,
        storage=get_storage(),
    )


class AnalysisRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    content_id: UUID
    benchmark_run_id: UUID
    snapshot_ids: list[str]
    status: Literal["pending", "running", "succeeded", "failed"]
    trigger_kind: Literal["manual", "auto"]
    report: AnalysisReport | None
    error_code: str | None
    model_config_id: UUID | None
    model_provider: str
    model_version: str
    provider_contract_version: str
    model_config_version: str
    prompt_version: str
    algorithm_version: str
    benchmark_algorithm_version: str
    created_at: datetime
    completed_at: datetime | None


class AnalysisSettingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_analyze: bool


class AnalysisSettingRead(BaseModel):
    auto_analyze: bool


class AnalysisFeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: Literal["useful", "not_useful"]


class ProductEventAck(BaseModel):
    id: UUID
    event_name: str


class AnalysisSuggestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    analysis_run_id: UUID
    recommendation_id: str
    recommendation: Recommendation
    adoption_status: Literal["saved", "adopted", "rejected"]
    created_at: datetime
    updated_at: datetime


class SuggestionAdoptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adoption_status: Literal["adopted", "rejected"]
