from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.analysis.models import AnalysisRun, AnalysisRunStatus
from app.modules.content.account_models import Platform
from app.modules.exports.report import render_analysis_markdown
from app.modules.metrics.models import BenchmarkRun, ContentType
from app.modules.workspace.auth import InviteAuthService
from tests.imports.helpers import (
    configured_client,
    create_published_content,
    create_workspace_account,
)


def _context(client, engine, workspace_id: str):
    token = client.cookies.get("session")
    assert token
    with Session(engine) as session:
        context = InviteAuthService(session).authenticate(token)
        assert context is not None
        assert str(context.workspace_id) == workspace_id
        return context


def _benchmark_run(
    session: Session,
    *,
    workspace_id: UUID,
    account_id: UUID,
) -> BenchmarkRun:
    run = BenchmarkRun(
        workspace_id=workspace_id,
        account_id=account_id,
        platform=Platform.DOUYIN,
        content_type=ContentType.VIDEO,
        maturity_bucket="24h",
        range_settings={"kind": "synthetic"},
        sample_snapshot_ids=[],
        sample_count=0,
        percentile_values={},
        weights={},
        confidence="raw_only",
        algorithm_version="benchmark-v1",
    )
    session.add(run)
    session.flush()
    return run


def test_markdown_report_separates_facts_ai_and_valid_citations() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        content = create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="合成分析报告",
            work_url="https://example.test/report",
        )
        context = _context(client, engine, workspace_id)
        with Session(engine, expire_on_commit=False) as session:
            benchmark = _benchmark_run(
                session,
                workspace_id=context.workspace_id,
                account_id=UUID(account["id"]),
            )
            run = AnalysisRun(
                workspace_id=context.workspace_id,
                account_id=UUID(account["id"]),
                content_id=UUID(content["id"]),
                benchmark_run_id=benchmark.id,
                snapshot_ids=[],
                status=AnalysisRunStatus.SUCCEEDED,
                trigger_kind="manual",
                cache_key="f" * 64,
                evidence_bundle={
                    "content": {
                        "id": content["id"],
                        "title": content["title"],
                        "body": content["body"],
                        "cover_asset_ids": [],
                        "cover_asset_metadata": [],
                    },
                    "snapshots": [],
                    "benchmark": {
                        "id": content["benchmark_profile_id"],
                        "sample_count": 0,
                        "confidence": "raw_only",
                        "percentiles": {},
                    },
                    "comparable_contents": [],
                    "items": [
                        {
                            "id": "content:title",
                            "kind": "content",
                            "label": "发布标题",
                            "value": "合成分析报告",
                            "source_id": content["id"],
                        }
                    ],
                    "trend_allowed": False,
                    "confidence_ceiling": "low",
                },
                model_version="mock-analysis-v1",
                prompt_version="analysis-prompt-v1",
                algorithm_version="analysis-v1",
                benchmark_algorithm_version="benchmark-v1",
                report={
                    "data_performance": {
                        "summary": "AI辅助判断：现有合成证据有限。",
                        "evidence_ids": ["content:title"],
                        "trend_conclusion": None,
                    },
                    "title_issues": [],
                    "copy_issues": [],
                    "cover_issues": [],
                    "evidence": [
                        {
                            "evidence_id": "content:title",
                            "interpretation": "仅引用本次证据包中的标题。",
                        },
                        {
                            "evidence_id": "outside:bundle",
                            "interpretation": "不得导出的伪造引用。",
                        },
                    ],
                    "causal_hypotheses": [],
                    "confidence": "low",
                    "recommendations": [],
                    "next_experiments": [],
                    "degradation_notice": "证据不足，已降级。",
                    "api_key": "sk-synthetic-secret-must-not-leak",
                    "session_token": "synthetic-session-token",
                },
                completed_at=datetime(2026, 7, 26, 2, 0, tzinfo=UTC),
            )
            session.add(run)
            session.commit()

            rendered = render_analysis_markdown(
                session, context, UUID(content["id"])
            )

        assert "# 合成分析报告" in rendered
        assert "## 确定性数据" in rendered
        assert "## AI 辅助判断" in rendered
        assert "mock-analysis-v1" in rendered
        assert "analysis-prompt-v1" in rendered
        assert "analysis-v1" in rendered
        assert "content:title" in rendered
        assert "仅引用本次证据包中的标题" in rendered
        assert "outside:bundle" not in rendered
        assert "伪造引用" not in rendered
        assert "sk-synthetic" not in rendered
        assert "synthetic-session-token" not in rendered
        assert "辅助判断，不保证通过平台审核" in rendered


def test_markdown_missing_analysis_or_evidence_fails_closed() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        content = create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="无证据合成内容",
            work_url=None,
        )
        context = _context(client, engine, workspace_id)
        with Session(engine) as session:
            rendered = render_analysis_markdown(
                session, context, UUID(content["id"])
            )

        assert "证据不足" in rendered
        assert "引用" not in rendered
        assert "辅助判断，不保证通过平台审核" in rendered


def test_markdown_rejects_ai_summary_with_unknown_evidence_ids() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        content = create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="摘要引用门禁",
            work_url=None,
        )
        context = _context(client, engine, workspace_id)
        with Session(engine, expire_on_commit=False) as session:
            benchmark = _benchmark_run(
                session,
                workspace_id=context.workspace_id,
                account_id=UUID(account["id"]),
            )
            session.add(
                AnalysisRun(
                    workspace_id=context.workspace_id,
                    account_id=UUID(account["id"]),
                    content_id=UUID(content["id"]),
                    benchmark_run_id=benchmark.id,
                    snapshot_ids=[],
                    status=AnalysisRunStatus.SUCCEEDED,
                    trigger_kind="manual",
                    cache_key="3" * 64,
                    evidence_bundle={
                        "items": [
                            {
                                "id": "content:title",
                                "kind": "content",
                                "label": "标题",
                                "value": "摘要引用门禁",
                            }
                        ]
                    },
                    model_version="mock",
                    prompt_version="prompt",
                    algorithm_version="analysis",
                    benchmark_algorithm_version="benchmark",
                    report={
                        "data_performance": {
                            "summary": "这段无依据摘要不得导出",
                            "evidence_ids": ["outside:bundle"],
                        },
                        "evidence": [],
                    },
                )
            )
            session.commit()
            rendered = render_analysis_markdown(
                session, context, UUID(content["id"])
            )

        assert "这段无依据摘要不得导出" not in rendered
        assert "证据不足，未生成判断" in rendered


def test_markdown_cross_workspace_content_is_not_discoverable() -> None:
    with configured_client() as (first, engine):
        first_workspace, first_csrf, account = create_workspace_account(first)
        content = create_published_content(
            first,
            workspace_id=first_workspace,
            csrf=first_csrf,
            account=account,
            title="工作区A合成内容",
            work_url=None,
        )
        other = first.post(
            "/v1/workspaces", json={"name": "工作区B"}
        ).json()
        other_client = type(first)(app=first.app)
        login = other_client.post(
            "/v1/sessions/invite",
            json={
                "code": other["admin_code"],
                "display_name": "工作区B管理员",
            },
        )
        assert login.status_code == 201
        context = _context(other_client, engine, other["workspace_id"])

        with Session(engine) as session:
            try:
                render_analysis_markdown(session, context, UUID(content["id"]))
            except LookupError as error:
                assert str(error) == "content not found"
            else:
                raise AssertionError("cross-workspace report must be hidden")
        other_client.close()


def test_report_selects_latest_successful_analysis_deterministically() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        content = create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="版本选择合成内容",
            work_url=None,
        )
        context = _context(client, engine, workspace_id)
        with Session(engine, expire_on_commit=False) as session:
            benchmark = _benchmark_run(
                session,
                workspace_id=context.workspace_id,
                account_id=UUID(account["id"]),
            )
            base = dict(
                workspace_id=context.workspace_id,
                account_id=UUID(account["id"]),
                content_id=UUID(content["id"]),
                benchmark_run_id=benchmark.id,
                snapshot_ids=[],
                status=AnalysisRunStatus.SUCCEEDED,
                trigger_kind="manual",
                evidence_bundle={
                    "items": [],
                    "content": {},
                    "snapshots": [],
                    "benchmark": {},
                    "comparable_contents": [],
                    "trend_allowed": False,
                    "confidence_ceiling": "low",
                },
                prompt_version="prompt-v1",
                algorithm_version="analysis-v1",
                benchmark_algorithm_version="benchmark-v1",
                report=None,
            )
            older = AnalysisRun(
                **base,
                cache_key="1" * 64,
                model_version="old-model",
                completed_at=datetime(2026, 7, 25, tzinfo=UTC),
            )
            latest = AnalysisRun(
                **base,
                cache_key="2" * 64,
                model_version="latest-model",
                completed_at=datetime(2026, 7, 26, tzinfo=UTC),
            )
            session.add_all([latest, older])
            session.commit()
            assert (
                session.scalar(
                    select(AnalysisRun)
                    .where(AnalysisRun.content_id == UUID(content["id"]))
                    .order_by(AnalysisRun.completed_at.desc())
                )
                is latest
            )
            rendered = render_analysis_markdown(
                session, context, UUID(content["id"])
            )

        assert "latest-model" in rendered
        assert "old-model" not in rendered
