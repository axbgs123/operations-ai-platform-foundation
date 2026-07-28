import asyncio
from typing import Literal, Protocol

from app.modules.analysis.features import AnalysisEvidenceBundle
from app.modules.analysis.schemas import AnalysisReport
from app.modules.models.capabilities import Capability, ModelRequest


class StructuredAnalysisProvider(Protocol):
    async def generate_structured(
        self,
        request: ModelRequest[AnalysisReport],
    ) -> AnalysisReport: ...


class QianwenAnalysisAdapter:
    model_version: str

    def __init__(
        self,
        provider: StructuredAnalysisProvider,
        *,
        platform: Literal["douyin", "xiaohongshu"],
        model_version: str = "qwen3.5-plus-2026-04-20",
    ) -> None:
        self._provider = provider
        self._platform = platform
        self.model_version = model_version

    def analyze(self, bundle: AnalysisEvidenceBundle) -> AnalysisReport:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError(
                "Qianwen analysis sync bridge cannot run in an existing event loop"
            )
        return asyncio.run(self._analyze(bundle))

    async def _analyze(
        self,
        bundle: AnalysisEvidenceBundle,
    ) -> AnalysisReport:
        return await self._provider.generate_structured(
            ModelRequest(
                capability=Capability.TEXT,
                prompt=(
                    "根据当前 Evidence Bundle 生成 AnalysisReport。"
                    "只能引用 allowed_evidence_ids；因果表述必须是待验证假设；"
                    "建议必须包含证据。封面只提供存在性信息，本阶段没有查看图片。"
                ),
                response_model=AnalysisReport,
                inputs=_safe_analysis_inputs(bundle, self._platform),
            )
        )


def _safe_analysis_inputs(
    bundle: AnalysisEvidenceBundle,
    platform: Literal["douyin", "xiaohongshu"],
) -> dict[str, object]:
    safe_evidence = []
    for item in bundle.items:
        value = (
            "存在封面素材；本阶段文本模型未查看图片"
            if item.kind == "cover" and bundle.content.cover_asset_ids
            else "未提供封面素材"
            if item.kind == "cover"
            else item.value
        )
        safe_evidence.append(
            {
                "id": item.id,
                "kind": item.kind,
                "label": item.label,
                "value": value,
            }
        )
    return {
        "platform": platform,
        "content": {
            "title": bundle.content.title,
            "body": bundle.content.body,
        },
        "cover": {
            "present": bool(bundle.content.cover_asset_ids),
            "count": len(bundle.content.cover_asset_ids),
            "visual_analysis_performed": False,
        },
        "evidence": safe_evidence,
        "allowed_evidence_ids": sorted(bundle.evidence_ids()),
        "benchmark_sample_count": bundle.benchmark.sample_count,
        "trend_allowed": bundle.trend_allowed,
        "confidence_ceiling": bundle.confidence_ceiling,
    }
