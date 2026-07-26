import re
from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.analysis.models import AnalysisRun, AnalysisRunStatus
from app.modules.content.models import Content
from app.modules.exports.tabular import isoformat_preserving_timezone


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
    run = session.scalar(
        select(AnalysisRun)
        .where(
            AnalysisRun.workspace_id == context.workspace_id,
            AnalysisRun.content_id == content.id,
            AnalysisRun.status == AnalysisRunStatus.SUCCEEDED,
        )
        .order_by(
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
