import re
from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.analysis.models import AnalysisRun, AnalysisRunStatus
from app.modules.content.models import Content
from app.modules.exports.tabular import isoformat_preserving_timezone
from app.modules.generation.models import TextGenerationRun
from app.modules.operations_agent.models import (
    AgentArtifact,
    AgentArtifactKind,
    AgentEvent,
    AgentRun,
)
from app.modules.risk_rag.models import RiskScan


DISCLAIMER = "辅助判断，不保证通过平台审核"
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~-]{8,}"),
    re.compile(
        r"(?i)\b(api[_ -]?key|invite[_ -]?code|session[_ -]?token)"
        r"\s*[:=]\s*\S+"
    ),
)


def _safe_text(value: object) -> str:
    text = str(value).replace("\x00", "")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def render_analysis_markdown(
    session: Session,
    context: WorkspaceContext,
    content_id: UUID,
    *,
    analysis_run_id: UUID | None = None,
) -> str:
    content = session.scalar(
        select(Content).where(
            Content.id == content_id,
            Content.workspace_id == context.workspace_id,
            Content.deleted_at.is_(None),
        )
    )
    if content is None:
        raise LookupError("content not found")
    run_query = select(AnalysisRun).where(
            AnalysisRun.workspace_id == context.workspace_id,
            AnalysisRun.content_id == content.id,
            AnalysisRun.status == AnalysisRunStatus.SUCCEEDED,
        )
    if analysis_run_id is not None:
        run_query = run_query.where(AnalysisRun.id == analysis_run_id)
    run = session.scalar(
        run_query.order_by(
            AnalysisRun.completed_at.desc().nullslast(),
            AnalysisRun.created_at.desc(),
            AnalysisRun.id.desc(),
        )
    )
    lines = [
        f"# {_safe_text(content.published_title if content.published_title is not None else content.title)}",
        "",
        "## 内容基础信息",
        "",
        f"- 内容 ID：`{content.id}`",
        f"- 平台：`{content.platform.value}`",
        f"- 内容类型：`{content.content_type.value}`",
        f"- 状态：`{content.status.value}`",
        f"- 发布时间：{isoformat_preserving_timezone(content.published_at) or '未发布'}",
        "",
        "## 分析版本",
        "",
    ]
    if run is None:
        lines.extend(
            [
                "- 证据不足：没有成功且可验证的分析记录。",
                "",
                "## 确定性数据",
                "",
                "证据不足",
                "",
                "## AI 辅助判断",
                "",
                "证据不足，未生成判断。",
                "",
                f"> {DISCLAIMER}",
                "",
            ]
        )
        return "\n".join(lines)

    lines.extend(
        [
            f"- 模型版本：`{_safe_text(run.model_version)}`",
            f"- Prompt 版本：`{_safe_text(run.prompt_version)}`",
            f"- 分析算法版本：`{_safe_text(run.algorithm_version)}`",
            f"- 基准算法版本：`{_safe_text(run.benchmark_algorithm_version)}`",
            "",
            "## 确定性数据",
            "",
        ]
    )
    bundle = _mapping(run.evidence_bundle)
    raw_items = bundle.get("items")
    items = [item for item in raw_items if isinstance(item, Mapping)] if isinstance(raw_items, list) else []
    evidence_by_id = {
        str(item["id"]): item
        for item in items
        if isinstance(item.get("id"), str)
    }
    if evidence_by_id:
        for evidence_id in sorted(evidence_by_id):
            item = evidence_by_id[evidence_id]
            lines.append(
                f"- `{_safe_text(evidence_id)}` "
                f"{_safe_text(item.get('label', '证据'))}："
                f"{_safe_text(item.get('value', ''))}"
            )
    else:
        lines.append("证据不足")

    report = _mapping(run.report)
    performance = _mapping(report.get("data_performance"))
    summary = performance.get("summary")
    raw_performance_ids = performance.get("evidence_ids")
    performance_ids = (
        {item for item in raw_performance_ids if isinstance(item, str)}
        if isinstance(raw_performance_ids, list)
        else set()
    )
    performance_is_supported = bool(performance_ids) and (
        performance_ids <= evidence_by_id.keys()
    )
    lines.extend(["", "## AI 辅助判断", ""])
    if (
        isinstance(summary, str)
        and summary.strip()
        and performance_is_supported
    ):
        lines.append(_safe_text(summary))
    else:
        lines.append("证据不足，未生成判断。")

    raw_citations = report.get("evidence")
    citations = (
        [item for item in raw_citations if isinstance(item, Mapping)]
        if isinstance(raw_citations, list)
        else []
    )
    valid_citations = [
        item
        for item in citations
        if isinstance(item.get("evidence_id"), str)
        and item["evidence_id"] in evidence_by_id
        and isinstance(item.get("interpretation"), str)
        and item["interpretation"].strip()
    ]
    if valid_citations:
        lines.extend(["", "## 有效引用", ""])
        for citation in valid_citations:
            lines.append(
                f"- `{_safe_text(citation['evidence_id'])}`："
                f"{_safe_text(citation['interpretation'])}"
            )
    elif evidence_by_id:
        lines.extend(["", "证据不足：没有有效引用。"])
    lines.extend(["", f"> {DISCLAIMER}", ""])
    return "\n".join(lines)


def render_agent_execution_markdown(
    session: Session,
    context: WorkspaceContext,
    content_id: UUID,
    run_id: UUID,
) -> str:
    content = session.scalar(
        select(Content).where(
            Content.id == content_id,
            Content.workspace_id == context.workspace_id,
            Content.deleted_at.is_(None),
        )
    )
    if content is None:
        raise LookupError("agent execution package not found")
    run = session.scalar(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.workspace_id == context.workspace_id,
            AgentRun.account_id == content.account_id,
            AgentRun.platform == content.platform,
        )
    )
    if run is None:
        raise LookupError("agent execution package not found")
    artifacts = list(
        session.scalars(
            select(AgentArtifact)
            .where(
                AgentArtifact.workspace_id == context.workspace_id,
                AgentArtifact.run_id == run.id,
            )
            .order_by(AgentArtifact.created_at, AgentArtifact.id)
        )
    )
    by_kind = {artifact.kind: artifact for artifact in artifacts}
    analysis_artifact = by_kind.get(AgentArtifactKind.ANALYSIS)
    lines = [
        "# 运营智能体执行包",
        "",
        f"- 执行 ID：`{run.id}`",
        f"- 内容 ID：`{content.id}`",
        f"- 平台：`{content.platform.value}`",
        f"- 执行状态：`{run.status.value}`",
        "- 已执行发布：否",
        "",
        "## 内容分析",
        "",
        (
            render_analysis_markdown(
                session,
                context,
                content.id,
                analysis_run_id=analysis_artifact.resource_id,
            )
            if analysis_artifact is not None
            else "证据不足：本次执行没有绑定分析产物。"
        ),
        "",
        "## 优化草稿",
        "",
    ]
    draft_artifact = by_kind.get(AgentArtifactKind.TEXT_DRAFT)
    draft = (
        session.get(TextGenerationRun, draft_artifact.resource_id)
        if draft_artifact is not None
        else None
    )
    if (
        draft is None
        or draft.workspace_id != context.workspace_id
        or draft.account_id != run.account_id
        or draft.final_title is None
        or draft.final_copy is None
    ):
        lines.append("证据不足：没有可验证的优化草稿。")
    else:
        lines.extend(
            [
                f"### 标题\n\n{_safe_text(draft.final_title)}",
                "",
                f"### 文案\n\n{_safe_text(draft.final_copy)}",
            ]
        )
    lines.extend(["", "## 封面建议", ""])
    cover = by_kind.get(AgentArtifactKind.COVER_RECOMMENDATION)
    recommendation = (
        _mapping(cover.safe_metadata.get("recommendation"))
        if cover is not None
        else {}
    )
    if recommendation:
        lines.extend(
            [
                f"- 来源：`{_safe_text(recommendation.get('source', 'programmatic'))}`",
                f"- 布局：`{_safe_text(recommendation.get('layout', 'title_first_safe_area'))}`",
                "- 说明：沿用账号风格，标题优先并保留安全区；"
                "构图、文字和素材一致性仍需人工确认。",
            ]
        )
    else:
        lines.append("当前记录未提供封面建议。")
    lines.extend(["", "## 风控复检", ""])
    scan_artifact = by_kind.get(AgentArtifactKind.RISK_SCAN)
    scan = (
        session.get(RiskScan, scan_artifact.resource_id)
        if scan_artifact is not None
        else None
    )
    if (
        scan is None
        or scan.workspace_id != context.workspace_id
        or scan.account_id != run.account_id
        or scan.content_id != content.id
    ):
        lines.append("证据不足：没有可验证的风控扫描。")
    else:
        lines.extend(
            [
                f"- 扫描 ID：`{scan.id}`",
                f"- 状态：`{scan.status.value}`",
                f"- 诊断：{', '.join(_safe_text(item) for item in scan.diagnostics) or '无'}",
            ]
        )
    summary_artifact = by_kind.get(AgentArtifactKind.EXECUTION_SUMMARY)
    summary = (
        session.get(AgentEvent, summary_artifact.resource_id)
        if summary_artifact is not None
        else None
    )
    lines.extend(["", "## 执行摘要", ""])
    if (
        summary is None
        or summary.workspace_id != context.workspace_id
        or summary.run_id != run.id
    ):
        lines.append("当前记录未提供执行摘要。")
    else:
        lines.extend(
            [
                "- 已完成分析、草稿、风控复检和导出任务创建。",
                "- 已执行发布：否",
            ]
        )
    lines.extend(["", f"> {DISCLAIMER}", ""])
    return "\n".join(lines)
