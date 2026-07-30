from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from app.modules.analytics.north_star import AnalyticsService
from app.modules.content.models import Content
from app.modules.risk_rag.models import (
    RiskScan,
    RiskScanNode,
    RiskScanStatus,
)
from app.modules.metrics.models import ContentType, DataSnapshot, SnapshotSource
from tests.imports.helpers import configured_client


FORBIDDEN_RESPONSE_KEYS = {
    "authorization",
    "body",
    "cookie",
    "document_body",
    "evidence_bundle",
    "input_snapshot",
    "matched_content",
    "model_key",
    "ocr_text",
    "prompt",
    "prompt_version",
    "secret",
    "token",
}


def _keys(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key.lower()
            yield from _keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _keys(nested)


def _create_workspace(client: TestClient, name: str) -> dict[str, str]:
    response = client.post("/v1/workspaces", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _login(client: TestClient, code: str, display_name: str) -> dict[str, str]:
    response = client.post(
        "/v1/sessions/invite",
        json={"code": code, "display_name": display_name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_account(
    client: TestClient,
    *,
    workspace_id: str,
    csrf: str,
    platform: str,
    name: str,
) -> dict[str, Any]:
    response = client.post(
        f"/v1/workspaces/{workspace_id}/accounts",
        headers={"X-CSRF-Token": csrf},
        json={
            "platform": platform,
            "name": name,
            "objectives": ["reach"],
            "metric_weights": {"views": 1},
            "benchmark_sample_size": 30,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_content(
    client: TestClient,
    *,
    workspace_id: str,
    csrf: str,
    account: dict[str, Any],
    title: str,
) -> dict[str, Any]:
    response = client.post(
        "/v1/contents",
        headers={"X-CSRF-Token": csrf},
        json={
            "workspace_id": workspace_id,
            "account_id": account["id"],
            "platform": account["platform"],
            "content_type": "video",
            "title": title,
            "body": "PRIVATE_OCR_SOURCE_TEXT must never leave the read model",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@contextmanager
def _seeded_workbench() -> Iterator[tuple[TestClient, object, dict[str, Any]]]:
    with configured_client() as (client, engine):
        private = _create_workspace(client, "合成运营工作区")
        foreign = _create_workspace(client, "其他合成工作区")

        foreign_login = _login(client, foreign["admin_code"], "其他管理员")
        foreign_account = _create_account(
            client,
            workspace_id=foreign["workspace_id"],
            csrf=foreign_login["csrf_token"],
            platform="douyin",
            name="其他工作区抖音",
        )

        admin_login = _login(client, private["admin_code"], "工作区管理员")
        douyin = _create_account(
            client,
            workspace_id=private["workspace_id"],
            csrf=admin_login["csrf_token"],
            platform="douyin",
            name="抖音合成账号",
        )
        douyin_secondary = _create_account(
            client,
            workspace_id=private["workspace_id"],
            csrf=admin_login["csrf_token"],
            platform="douyin",
            name="抖音合成账号二",
        )
        xiaohongshu = _create_account(
            client,
            workspace_id=private["workspace_id"],
            csrf=admin_login["csrf_token"],
            platform="xiaohongshu",
            name="小红书合成账号",
        )
        douyin_content = _create_content(
            client,
            workspace_id=private["workspace_id"],
            csrf=admin_login["csrf_token"],
            account=douyin,
            title="抖音待分析内容",
        )
        xiaohongshu_content = _create_content(
            client,
            workspace_id=private["workspace_id"],
            csrf=admin_login["csrf_token"],
            account=xiaohongshu,
            title="小红书待分析内容",
        )

        with Session(engine) as session:
            session.add_all(
                [
                    RiskScan(
                        workspace_id=UUID(private["workspace_id"]),
                        account_id=UUID(douyin["id"]),
                        content_id=UUID(douyin_content["id"]),
                        platform="douyin",
                        node=RiskScanNode.BEFORE_PUBLICATION,
                        status=RiskScanStatus.SUCCEEDED,
                        idempotency_key="workbench-risk-scan",
                        input_fingerprint="a" * 64,
                        input_snapshot={
                            "ocr_text": "PRIVATE_OCR_SOURCE_TEXT",
                            "prompt": "PRIVATE_PROMPT",
                        },
                        rule_version="rules-v1",
                        evidence_version="evidence-v1",
                        embedding_model_id="mock-embedding",
                        embedding_version="embedding-v1",
                        embedding_dimension=3,
                        rag_model_version="mock-rag-v1",
                        scanner_version="scanner-v1",
                        result={
                            "findings": [
                                {
                                    "risk_type": "synthetic_high_risk",
                                    "severity": "high",
                                    "matched_content": "PRIVATE_MATCHED_CONTENT",
                                }
                            ],
                            "ocr_status": "succeeded",
                        },
                        diagnostics=[],
                        requested_by=UUID(admin_login["member_id"]),
                    ),
                    RiskScan(
                        workspace_id=UUID(private["workspace_id"]),
                        account_id=UUID(xiaohongshu["id"]),
                        content_id=UUID(xiaohongshu_content["id"]),
                        platform="xiaohongshu",
                        node=RiskScanNode.BEFORE_PUBLICATION,
                        status=RiskScanStatus.FAILED,
                        idempotency_key="workbench-failed-risk-scan",
                        input_fingerprint="b" * 64,
                        input_snapshot={"body": "PRIVATE_FAILED_INPUT"},
                        rule_version="rules-v1",
                        evidence_version="evidence-v1",
                        embedding_model_id="mock-embedding",
                        embedding_version="embedding-v1",
                        embedding_dimension=3,
                        rag_model_version="mock-rag-v1",
                        scanner_version="scanner-v1",
                        result=None,
                        error_code="SYNTHETIC_FAILURE",
                        diagnostics=[],
                        requested_by=UUID(admin_login["member_id"]),
                    ),
                ]
            )
            session.commit()

        viewer_code = client.post(
            f"/v1/workspaces/{private['workspace_id']}/members/codes",
            headers={"X-CSRF-Token": admin_login["csrf_token"]},
            json={"role": "viewer"},
        )
        assert viewer_code.status_code == 201, viewer_code.text
        viewer_login = _login(
            client,
            viewer_code.json()["code"],
            "只读查看者",
        )

        yield (
            client,
            engine,
            {
                "workspace": private,
                "foreign": foreign,
                "foreign_account": foreign_account,
                "viewer_login": viewer_login,
                "douyin": douyin,
                "douyin_secondary": douyin_secondary,
                "xiaohongshu": xiaohongshu,
                "douyin_content": douyin_content,
                "xiaohongshu_content": xiaohongshu_content,
            },
        )


def test_viewer_reads_context_and_overview_without_combined_platform_metrics() -> None:
    with _seeded_workbench() as (client, _, seeded):
        workspace_id = seeded["workspace"]["workspace_id"]

        context_response = client.get(
            f"/v1/workspaces/{workspace_id}/workbench/context"
        )
        assert context_response.status_code == 200, context_response.text
        context = context_response.json()
        assert context["workspace_id"] == workspace_id
        assert context["workspace_name"] == "合成运营工作区"
        assert context["member_id"] == seeded["viewer_login"]["member_id"]
        assert context["member_display_name"] == "只读查看者"
        assert context["role"] == "viewer"
        assert {account["platform"] for account in context["accounts"]} == {
            "douyin",
            "xiaohongshu",
        }
        assert context["failed_task_count"] == 1

        overview_response = client.get(
            f"/v1/workspaces/{workspace_id}/workbench/overview"
        )
        assert overview_response.status_code == 200, overview_response.text
        overview = overview_response.json()
        assert set(overview) == {
            "data_status",
            "attention",
            "next_action",
            "accounts",
        }
        assert {account["platform"] for account in overview["accounts"]} == {
            "douyin",
            "xiaohongshu",
        }
        assert all(
            account["confirmed_snapshot_count"] == 0
            and account["latest_maturity_bucket"] is None
            for account in overview["accounts"]
        )
        forbidden_aggregates = {
            "total_views",
            "combined_metrics",
            "impressions",
            "ctr",
            "combined_trend",
            "cross_platform_score",
        }
        assert forbidden_aggregates.isdisjoint(_keys(overview))
        assert FORBIDDEN_RESPONSE_KEYS.isdisjoint(_keys(overview))


def test_queues_require_platform_and_keep_platform_rows_separate() -> None:
    with _seeded_workbench() as (client, _, seeded):
        workspace_id = seeded["workspace"]["workspace_id"]

        missing_platform = client.get(
            f"/v1/workspaces/{workspace_id}/workbench/analysis-queue"
        )
        assert missing_platform.status_code == 422

        douyin_analysis = client.get(
            f"/v1/workspaces/{workspace_id}/workbench/analysis-queue",
            params={"platform": "douyin"},
        )
        assert douyin_analysis.status_code == 200, douyin_analysis.text
        assert {row["content_id"] for row in douyin_analysis.json()["items"]} == {
            seeded["douyin_content"]["id"]
        }
        assert {row["platform"] for row in douyin_analysis.json()["items"]} == {
            "douyin"
        }

        xiaohongshu_analysis = client.get(
            f"/v1/workspaces/{workspace_id}/workbench/analysis-queue",
            params={"platform": "xiaohongshu"},
        )
        assert xiaohongshu_analysis.status_code == 200
        assert {row["content_id"] for row in xiaohongshu_analysis.json()["items"]} == {
            seeded["xiaohongshu_content"]["id"]
        }
        assert {row["platform"] for row in xiaohongshu_analysis.json()["items"]} == {
            "xiaohongshu"
        }

        douyin_preflight = client.get(
            f"/v1/workspaces/{workspace_id}/workbench/preflight-queue",
            params={"platform": "douyin"},
        )
        assert douyin_preflight.status_code == 200, douyin_preflight.text
        assert {row["content_id"] for row in douyin_preflight.json()["items"]} == {
            seeded["douyin_content"]["id"]
        }
        assert (
            douyin_preflight.json()["items"][0]["status"]
            == "high_risk_blocked"
        )

        xiaohongshu_preflight = client.get(
            f"/v1/workspaces/{workspace_id}/workbench/preflight-queue",
            params={"platform": "xiaohongshu"},
        )
        assert xiaohongshu_preflight.status_code == 200
        assert {row["content_id"] for row in xiaohongshu_preflight.json()["items"]} == {
            seeded["xiaohongshu_content"]["id"]
        }
        assert xiaohongshu_preflight.json()["items"][0]["status"] == "scan_failed"

        for response in (
            douyin_analysis,
            xiaohongshu_analysis,
            douyin_preflight,
            xiaohongshu_preflight,
        ):
            assert FORBIDDEN_RESPONSE_KEYS.isdisjoint(_keys(response.json()))
            assert "PRIVATE_" not in response.text


def test_overview_scope_keeps_platform_accounts_and_attention_separate() -> None:
    with _seeded_workbench() as (client, engine, seeded):
        workspace_id = seeded["workspace"]["workspace_id"]
        with Session(engine) as session:
            session.add_all(
                [
                    DataSnapshot(
                        workspace_id=UUID(workspace_id),
                        content_id=UUID(seeded["douyin_content"]["id"]),
                        account_id=UUID(seeded["douyin"]["id"]),
                        platform="douyin",
                        content_type=ContentType.VIDEO,
                        collected_at=datetime(2026, 7, 29, tzinfo=UTC),
                        age_seconds=86_400,
                        maturity_bucket="24h",
                        source=SnapshotSource.MANUAL,
                        confirmed=True,
                        analytics_eligible=True,
                    ),
                    DataSnapshot(
                        workspace_id=UUID(workspace_id),
                        content_id=UUID(seeded["xiaohongshu_content"]["id"]),
                        account_id=UUID(seeded["xiaohongshu"]["id"]),
                        platform="xiaohongshu",
                        content_type=ContentType.VIDEO,
                        collected_at=datetime(2026, 7, 29, tzinfo=UTC),
                        age_seconds=259_200,
                        maturity_bucket="72h",
                        source=SnapshotSource.MANUAL,
                        confirmed=True,
                        analytics_eligible=True,
                    ),
                ]
            )
            session.commit()

        douyin = client.get(
            f"/v1/workspaces/{workspace_id}/workbench/overview",
            params={
                "platform": "douyin",
                "account_id": seeded["douyin"]["id"],
            },
        )
        assert douyin.status_code == 200, douyin.text
        payload = douyin.json()
        assert [item["account_id"] for item in payload["accounts"]] == [
            seeded["douyin"]["id"]
        ]
        assert payload["attention"]["pending_analysis_count"] == 1
        assert payload["attention"]["high_risk_count"] == 1
        assert payload["accounts"][0]["confirmed_snapshot_count"] == 1
        assert payload["accounts"][0]["latest_maturity_bucket"] == "24h"
        assert payload["data_status"][
            "accounts_missing_recommended_snapshot"
        ] == 1

        mismatched = client.get(
            f"/v1/workspaces/{workspace_id}/workbench/overview",
            params={
                "platform": "douyin",
                "account_id": seeded["xiaohongshu"]["id"],
            },
        )
        assert mismatched.status_code == 404


def test_closed_loop_status_is_attributed_to_the_evidence_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _seeded_workbench() as (client, _, seeded):
        current = datetime.now(UTC).astimezone()
        year, week, _ = current.isocalendar()
        monkeypatch.setattr(
            AnalyticsService,
            "effective_loops",
            lambda _service: [
                SimpleNamespace(
                    platform="douyin",
                    iso_week=f"{year}-W{week:02d}",
                    evidence_ids={
                        "content_id": seeded["douyin_content"]["id"],
                    },
                )
            ],
        )

        response = client.get(
            "/v1/workspaces/"
            f"{seeded['workspace']['workspace_id']}/workbench/overview"
        )
        assert response.status_code == 200, response.text
        accounts = {
            item["account_id"]: item
            for item in response.json()["accounts"]
        }
        assert accounts[seeded["douyin"]["id"]][
            "has_current_week_closed_loop"
        ] is True
        assert accounts[seeded["douyin_secondary"]["id"]][
            "has_current_week_closed_loop"
        ] is False


def test_queue_filters_reject_foreign_or_platform_mismatched_accounts() -> None:
    with _seeded_workbench() as (client, _, seeded):
        workspace_id = seeded["workspace"]["workspace_id"]
        for queue_name in ("analysis-queue", "preflight-queue"):
            path = f"/v1/workspaces/{workspace_id}/workbench/{queue_name}"
            foreign = client.get(
                path,
                params={
                    "platform": "douyin",
                    "account_id": seeded["foreign_account"]["id"],
                },
            )
            assert foreign.status_code == 404

            mismatched = client.get(
                path,
                params={
                    "platform": "douyin",
                    "account_id": seeded["xiaohongshu"]["id"],
                },
            )
            assert mismatched.status_code == 404


def test_cross_workspace_and_demo_cannot_read_private_workbench() -> None:
    with _seeded_workbench() as (client, _, seeded):
        foreign_workspace_id = seeded["foreign"]["workspace_id"]
        for endpoint, params in (
            ("context", None),
            ("overview", None),
            ("analysis-queue", {"platform": "douyin"}),
            ("preflight-queue", {"platform": "douyin"}),
        ):
            cross_workspace = client.get(
                f"/v1/workspaces/{foreign_workspace_id}/workbench/{endpoint}",
                params=params,
            )
            assert cross_workspace.status_code == 404

        client.cookies.clear()
        demo_session = client.post("/v1/demo/sessions")
        assert demo_session.status_code == 201
        private_workspace_id = seeded["workspace"]["workspace_id"]
        demo_private = client.get(
            f"/v1/workspaces/{private_workspace_id}/workbench/context"
        )
        assert demo_private.status_code in {401, 403}
        assert "合成运营工作区" not in demo_private.text


def test_analysis_queue_is_stably_paginated_and_status_scoped() -> None:
    with _seeded_workbench() as (client, engine, seeded):
        workspace_id = seeded["workspace"]["workspace_id"]
        expected_ids = {seeded["douyin_content"]["id"]}
        fixed_created_at = datetime(2026, 7, 29, 8, 0, tzinfo=UTC)
        with Session(engine) as session:
            source = session.get(Content, UUID(seeded["douyin_content"]["id"]))
            assert source is not None
            source.created_at = fixed_created_at
            for index in range(3):
                content = Content(
                    workspace_id=source.workspace_id,
                    account_id=source.account_id,
                    platform=source.platform,
                    title=f"分页合成内容 {index}",
                    body="不得进入分析队列响应的完整文案",
                    objective_profile_id=source.objective_profile_id,
                    benchmark_profile_id=source.benchmark_profile_id,
                    content_type=source.content_type,
                )
                content.created_at = fixed_created_at
                session.add(content)
                session.flush()
                expected_ids.add(str(content.id))
            session.commit()

        first = client.get(
            f"/v1/workspaces/{workspace_id}/workbench/analysis-queue",
            params={
                "platform": "douyin",
                "status": "pending",
                "sort": "newest",
                "page": 1,
                "page_size": 2,
            },
        )
        assert first.status_code == 200, first.text
        first_page = first.json()
        assert set(first_page) == {
            "platform",
            "account_id",
            "status",
            "sort",
            "page",
            "page_size",
            "total",
            "pages",
            "items",
        }
        assert first_page["platform"] == "douyin"
        assert first_page["status"] == "pending"
        assert first_page["page"] == 1
        assert first_page["page_size"] == 2
        assert first_page["total"] == 4
        assert len(first_page["items"]) == 2
        assert all(item["status"] == "pending" for item in first_page["items"])

        second = client.get(
            f"/v1/workspaces/{workspace_id}/workbench/analysis-queue",
            params={
                "platform": "douyin",
                "status": "pending",
                "sort": "newest",
                "page": 2,
                "page_size": 2,
            },
        )
        assert second.status_code == 200, second.text
        second_page = second.json()
        returned_ids = [
            item["content_id"]
            for item in first_page["items"] + second_page["items"]
        ]
        assert set(returned_ids) == expected_ids
        assert len(returned_ids) == len(set(returned_ids))
        assert returned_ids == sorted(returned_ids, reverse=True)

        for status in (
            "pending",
            "running",
            "completed",
            "insufficient_sample",
            "failed",
            "configuration_required",
            "suggestion_pending",
        ):
            response = client.get(
                f"/v1/workspaces/{workspace_id}/workbench/analysis-queue",
                params={"platform": "douyin", "status": status},
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == status

        too_large = client.get(
            f"/v1/workspaces/{workspace_id}/workbench/analysis-queue",
            params={"platform": "douyin", "page_size": 101},
        )
        assert too_large.status_code == 422
        invalid_status = client.get(
            f"/v1/workspaces/{workspace_id}/workbench/analysis-queue",
            params={"platform": "douyin", "status": "all"},
        )
        assert invalid_status.status_code == 422

        assert FORBIDDEN_RESPONSE_KEYS.isdisjoint(_keys(first_page))
        assert "不得进入分析队列响应的完整文案" not in first.text


def test_preflight_queue_is_bounded_stable_and_status_scoped() -> None:
    with _seeded_workbench() as (client, engine, seeded):
        workspace_id = seeded["workspace"]["workspace_id"]
        expected_pending_ids: set[str] = set()
        fixed_created_at = datetime(2026, 7, 29, 9, 0, tzinfo=UTC)
        with Session(engine) as session:
            source = session.get(Content, UUID(seeded["douyin_content"]["id"]))
            assert source is not None
            for index in range(3):
                content = Content(
                    workspace_id=source.workspace_id,
                    account_id=source.account_id,
                    platform=source.platform,
                    title=f"发布前分页内容 {index}",
                    body="PRIVATE_PREFLIGHT_BODY must never leave the queue",
                    objective_profile_id=source.objective_profile_id,
                    benchmark_profile_id=source.benchmark_profile_id,
                    content_type=source.content_type,
                )
                content.created_at = fixed_created_at
                session.add(content)
                session.flush()
                expected_pending_ids.add(str(content.id))
            session.commit()

        first = client.get(
            f"/v1/workspaces/{workspace_id}/workbench/preflight-queue",
            params={
                "platform": "douyin",
                "status": "pending_scan",
                "sort": "newest",
                "page": 1,
                "page_size": 2,
            },
        )
        assert first.status_code == 200, first.text
        first_page = first.json()
        assert set(first_page) == {
            "platform",
            "account_id",
            "status",
            "sort",
            "page",
            "page_size",
            "total",
            "pages",
            "items",
        }
        assert first_page["status"] == "pending_scan"
        assert first_page["page"] == 1
        assert first_page["page_size"] == 2
        assert first_page["total"] == 3
        assert len(first_page["items"]) == 2

        second = client.get(
            f"/v1/workspaces/{workspace_id}/workbench/preflight-queue",
            params={
                "platform": "douyin",
                "status": "pending_scan",
                "sort": "newest",
                "page": 2,
                "page_size": 2,
            },
        )
        assert second.status_code == 200, second.text
        returned_ids = [
            item["content_id"]
            for item in first_page["items"] + second.json()["items"]
        ]
        assert set(returned_ids) == expected_pending_ids
        assert len(returned_ids) == len(set(returned_ids))
        assert returned_ids == sorted(returned_ids, reverse=True)

        for status in (
            "pending_scan",
            "high_risk_blocked",
            "low_confidence_ocr",
            "no_active_rag_evidence",
            "modified_awaiting_rescan",
            "manually_confirmed",
            "review_required",
            "scan_failed",
        ):
            response = client.get(
                f"/v1/workspaces/{workspace_id}/workbench/preflight-queue",
                params={"platform": "douyin", "status": status},
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == status

        too_large = client.get(
            f"/v1/workspaces/{workspace_id}/workbench/preflight-queue",
            params={"platform": "douyin", "page_size": 101},
        )
        assert too_large.status_code == 422
        invalid_status = client.get(
            f"/v1/workspaces/{workspace_id}/workbench/preflight-queue",
            params={"platform": "douyin", "status": "safe"},
        )
        assert invalid_status.status_code == 422
        assert FORBIDDEN_RESPONSE_KEYS.isdisjoint(_keys(first_page))
        assert "PRIVATE_PREFLIGHT_BODY" not in first.text


def test_preflight_queue_derives_fail_closed_review_states() -> None:
    with _seeded_workbench() as (client, engine, seeded):
        workspace_id = seeded["workspace"]["workspace_id"]
        expected: dict[str, str] = {}
        with Session(engine) as session:
            source = session.get(Content, UUID(seeded["douyin_content"]["id"]))
            assert source is not None

            def add_scanned(
                label: str,
                expected_status: str,
                *,
                diagnostics: list[str] | None = None,
                findings: list[dict[str, object]] | None = None,
                result_error: str | None = None,
                modified: bool = False,
            ) -> None:
                content = Content(
                    workspace_id=source.workspace_id,
                    account_id=source.account_id,
                    platform=source.platform,
                    title=f"合成发布前状态 {label}",
                    body="人工合成且不应出现在队列响应的正文",
                    objective_profile_id=source.objective_profile_id,
                    benchmark_profile_id=source.benchmark_profile_id,
                    content_type=source.content_type,
                )
                session.add(content)
                session.flush()
                scan = RiskScan(
                    workspace_id=source.workspace_id,
                    account_id=source.account_id,
                    content_id=content.id,
                    platform=source.platform,
                    node=RiskScanNode.BEFORE_PUBLICATION,
                    status=RiskScanStatus.SUCCEEDED,
                    idempotency_key=f"task-8-{label}",
                    input_fingerprint=(label[0] * 64),
                    input_snapshot={"synthetic": True},
                    rule_version="rules-v1",
                    evidence_version="evidence-v1",
                    embedding_model_id="mock-embedding",
                    embedding_version="embedding-v1",
                    embedding_dimension=3,
                    rag_model_version="mock-rag-v1",
                    scanner_version="scanner-v1",
                    result={
                        "findings": findings or [],
                        "ocr_status": "succeeded",
                        **({"error_code": result_error} if result_error else {}),
                    },
                    diagnostics=diagnostics or [],
                    requested_by=None,
                )
                session.add(scan)
                session.flush()
                if modified:
                    content.updated_at = scan.created_at + timedelta(microseconds=1)
                expected[str(content.id)] = expected_status

            add_scanned(
                "low-ocr",
                "low_confidence_ocr",
                diagnostics=["OCR_LOW_CONFIDENCE"],
            )
            add_scanned(
                "no-evidence",
                "no_active_rag_evidence",
                result_error="NO_ACTIVE_RISK_EVIDENCE",
            )
            add_scanned(
                "manual",
                "manually_confirmed",
                diagnostics=["HUMAN_CONFIRMED"],
            )
            add_scanned("review", "review_required")
            add_scanned(
                "modified",
                "modified_awaiting_rescan",
                modified=True,
            )
            add_scanned(
                "modified-high-risk",
                "high_risk_blocked",
                findings=[
                    {
                        "risk_type": "synthetic_high_risk",
                        "severity": "high",
                        "requires_human_review": True,
                    }
                ],
                modified=True,
            )
            session.commit()

        response = client.get(
            f"/v1/workspaces/{workspace_id}/workbench/preflight-queue",
            params={"platform": "douyin", "page_size": 100},
        )
        assert response.status_code == 200, response.text
        by_id = {
            item["content_id"]: item["status"]
            for item in response.json()["items"]
        }
        assert {content_id: by_id[content_id] for content_id in expected} == expected
        assert "人工合成且不应出现在队列响应的正文" not in response.text
