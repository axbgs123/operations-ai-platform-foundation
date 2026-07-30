from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

from fastapi.testclient import TestClient

from app.modules.content.models import Content
from app.modules.metrics.dashboard import DashboardService, SnapshotSample
from app.modules.metrics.models import DataSnapshot
from tests.imports.helpers import configured_client


def create_dashboard_account(
    client: TestClient,
    *,
    platform: str = "xiaohongshu",
) -> tuple[str, str, dict]:
    workspace = client.post(
        "/v1/workspaces", json={"name": "合成仪表盘工作区"}
    ).json()
    login = client.post(
        "/v1/sessions/invite",
        json={"code": workspace["admin_code"], "display_name": "仪表盘管理员"},
    ).json()
    account = client.post(
        f"/v1/workspaces/{workspace['workspace_id']}/accounts",
        headers={"X-CSRF-Token": login["csrf_token"]},
        json={
            "platform": platform,
            "name": f"{platform} 仪表盘账号",
            "objectives": ["reach", "engagement", "growth"],
            "metric_weights": {
                "impressions" if platform == "xiaohongshu" else "views": 0.4,
                "views" if platform == "xiaohongshu" else "likes": 0.3,
                "likes" if platform == "xiaohongshu" else "comments": 0.2,
                "followers_gained": 0.1,
            },
            "benchmark_sample_size": 30,
        },
    ).json()
    return workspace["workspace_id"], login["csrf_token"], account


def add_dashboard_sample(
    client: TestClient,
    *,
    workspace_id: str,
    csrf: str,
    account: dict,
    index: int,
    content_type: str = "image_text",
    include_primary_metric: bool = True,
    include_secondary_metric: bool = True,
) -> None:
    metrics = (
        {
            "impressions": 2_000 + index * 100,
            "views": 1_000 + index * 80,
            "likes": 100 + index * 10,
            "followers_gained": 5 + index,
        }
        if account["platform"] == "xiaohongshu"
        else {
            "views": 1_000 + index * 80,
            "likes": 100 + index * 10,
            "comments": 20 + index,
            "followers_gained": 5 + index,
        }
    )
    if not include_primary_metric:
        metrics.pop("impressions" if account["platform"] == "xiaohongshu" else "views")
    if not include_secondary_metric:
        metrics.pop("views" if account["platform"] == "xiaohongshu" else "likes")
    content = client.post(
        "/v1/contents",
        headers={"X-CSRF-Token": csrf},
        json={
            "workspace_id": workspace_id,
            "account_id": account["id"],
            "platform": account["platform"],
            "content_type": content_type,
            "title": f"合成仪表盘内容 {index}",
            "body": "仅用于自动化测试",
        },
    ).json()
    published = client.patch(
        f"/v1/contents/{content['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"status": "published"},
    ).json()
    collected_at = datetime.fromisoformat(published["published_at"]) + timedelta(
        hours=24
    )
    snapshot = client.post(
        f"/v1/contents/{content['id']}/snapshots",
        headers={"X-CSRF-Token": csrf},
        json={
            "collected_at": collected_at.astimezone(UTC).isoformat(),
            "source": "manual",
            "metrics": [
                {"key": key, "raw_value": value}
                for key, value in metrics.items()
            ],
        },
    ).json()
    confirmed = client.post(
        f"/v1/contents/{content['id']}/snapshots/{snapshot['id']}/confirm",
        headers={"X-CSRF-Token": csrf},
    )
    assert confirmed.status_code == 200, confirmed.text


def test_small_sample_returns_raw_cards_and_two_snapshot_trend() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = create_dashboard_account(client)
        for index in range(4):
            add_dashboard_sample(
                client,
                workspace_id=workspace_id,
                csrf=csrf,
                account=account,
                index=index,
            )

        response = client.get(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/dashboard",
            params={"content_type": "image_text", "maturity_bucket": "24h"},
        )

        assert response.status_code == 200, response.text
        dashboard = response.json()
        assert 4 <= len(dashboard["goal_cards"]) <= 6
        assert dashboard["sample_count"] == 4
        assert dashboard["data_completeness"] == 1.0
        assert dashboard["confidence"] == "raw_only"
        assert "实际样本 4 条" in dashboard["explanation"]
        assert {chart["kind"] for chart in dashboard["charts"]} == {"line"}
        assert dashboard["benchmark_sample_size"] == 30
        assert dashboard["benchmark_bands"] == []
        gates = {gate["kind"]: gate for gate in dashboard["chart_gates"]}
        assert gates["line"] == {
            "kind": "line",
            "eligible": True,
            "reason": "同口径有效快照满足趋势展示条件。",
            "actual_sample_count": 4,
            "required_sample_count": 2,
            "missing_metric_keys": [],
        }
        assert gates["funnel"]["eligible"] is False
        assert gates["heatmap"]["eligible"] is False
        assert dashboard["next_actions"]
        assert all(
            card["drill_down_filter"]["account_id"] == account["id"]
            for card in dashboard["goal_cards"]
        )


def test_sufficient_data_returns_only_conditionally_valid_single_unit_charts() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = create_dashboard_account(client)
        for index in range(10):
            add_dashboard_sample(
                client,
                workspace_id=workspace_id,
                csrf=csrf,
                account=account,
                index=index,
            )

        response = client.get(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/dashboard",
            params={"content_type": "image_text", "maturity_bucket": "24h"},
        )

        assert response.status_code == 200, response.text
        dashboard = response.json()
        assert dashboard["sample_count"] == 10
        assert dashboard["data_completeness"] == 1.0
        assert dashboard["confidence"] == "normal"
        by_kind = {chart["kind"]: chart for chart in dashboard["charts"]}
        assert set(by_kind) == {"line", "funnel", "heatmap"}
        assert len(by_kind["line"]["points"]) == 10
        assert by_kind["line"]["title"] == "账号曝光量表现趋势"
        assert "每条内容最新一条同口径快照" in by_kind["line"]["explanation"]
        assert [point["x"] for point in by_kind["funnel"]["points"]] == [
            "曝光量",
            "阅读/播放量",
        ]
        assert all("y_axes" not in chart for chart in dashboard["charts"])
        assert all(isinstance(chart["unit"], str) for chart in dashboard["charts"])
        assert all(
            chart["drill_down_filter"]["content_type"] == "image_text"
            for chart in dashboard["charts"]
        )
        assert {item["kind"] for item in dashboard["attention_items"]} == {
            "candidate",
            "anomaly",
        }
        assert all(
            item["drill_down_filter"]["attention"] == item["kind"]
            for item in dashboard["attention_items"]
        )
        assert dashboard["benchmark_sample_size"] == 30
        impressions_band = next(
            band
            for band in dashboard["benchmark_bands"]
            if band["metric_key"] == "impressions"
        )
        assert impressions_band == {
            "metric_key": "impressions",
            "label": "曝光量",
            "unit": "count",
            "sample_count": 10,
            "median": 2450.0,
            "top_25": 2675.0,
            "top_10": 2810.0,
        }
        assert all(
            gate["eligible"]
            for gate in dashboard["chart_gates"]
        )


def test_funnel_is_omitted_when_platform_has_no_exposure_metric() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = create_dashboard_account(
            client, platform="douyin"
        )
        for index in range(10):
            add_dashboard_sample(
                client,
                workspace_id=workspace_id,
                csrf=csrf,
                account=account,
                index=index,
                content_type="video",
            )

        response = client.get(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/dashboard",
            params={"content_type": "video", "maturity_bucket": "24h"},
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert {chart["kind"] for chart in payload["charts"]} == {
            "line",
            "heatmap",
        }
        funnel_gate = next(
            gate for gate in payload["chart_gates"] if gate["kind"] == "funnel"
        )
        assert funnel_gate["eligible"] is False
        assert funnel_gate["missing_metric_keys"] == ["impressions"]
        assert "当前平台或内容类型不提供" in funnel_gate["reason"]


def test_chart_eligibility_uses_actual_usable_metric_samples() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = create_dashboard_account(client)
        for index in range(5):
            add_dashboard_sample(
                client,
                workspace_id=workspace_id,
                csrf=csrf,
                account=account,
                index=index,
                include_primary_metric=index < 2,
            )

        response = client.get(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/dashboard",
            params={"content_type": "image_text", "maturity_bucket": "24h"},
        )

        assert response.status_code == 200, response.text
        dashboard = response.json()
        impressions = next(
            card for card in dashboard["goal_cards"]
            if card["metric_key"] == "impressions"
        )
        assert impressions["sample_count"] == 2
        assert "有效样本 2 条" in impressions["explanation"]
        assert impressions["historical_percentile"] is None
        assert {chart["kind"] for chart in dashboard["charts"]} == {"line"}
        line_gate = next(
            gate for gate in dashboard["chart_gates"] if gate["kind"] == "line"
        )
        assert line_gate["actual_sample_count"] == 2
        assert line_gate["eligible"] is True
        assert line_gate["required_sample_count"] == 2


def test_dashboard_drill_down_applies_metric_maturity_and_attention() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = create_dashboard_account(client)
        for index in range(10):
            add_dashboard_sample(
                client,
                workspace_id=workspace_id,
                csrf=csrf,
                account=account,
                index=index,
            )

        path = (
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}"
            "/dashboard/contents"
        )
        common = {
            "content_type": "image_text",
            "maturity_bucket": "24h",
            "metric_key": "impressions",
        }
        candidate = client.get(path, params={**common, "attention": "candidate"})
        anomaly = client.get(path, params={**common, "attention": "anomaly"})

        assert candidate.status_code == 200, candidate.text
        assert anomaly.status_code == 200, anomaly.text
        assert [item["title"] for item in candidate.json()] == [
            "合成仪表盘内容 9"
        ]
        assert [item["title"] for item in anomaly.json()] == [
            "合成仪表盘内容 0"
        ]


def test_funnel_drill_down_returns_only_paired_metric_samples() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = create_dashboard_account(client)
        for index in range(10):
            add_dashboard_sample(
                client,
                workspace_id=workspace_id,
                csrf=csrf,
                account=account,
                index=index,
                include_secondary_metric=index != 9,
            )

        response = client.get(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}"
            "/dashboard/contents",
            params=[
                ("content_type", "image_text"),
                ("maturity_bucket", "24h"),
                ("required_metric_keys", "impressions"),
                ("required_metric_keys", "views"),
            ],
        )

        assert response.status_code == 200, response.text
        assert len(response.json()) == 9
        assert "合成仪表盘内容 9" not in {
            item["title"] for item in response.json()
        }


def test_lower_is_better_attention_uses_directional_percentile_evidence() -> None:
    workspace_id = uuid4()
    account_id = uuid4()
    samples = [
        SnapshotSample(
            snapshot=cast(DataSnapshot, SimpleNamespace()),
            content=cast(
                Content,
                SimpleNamespace(id=uuid4(), title=f"跳出率样本 {index}"),
            ),
            values={"bounce_rate_2s": Decimal(index + 1) / Decimal(100)},
        )
        for index in range(10)
    ]

    items = DashboardService._attention_items(
        samples,
        "bounce_rate_2s",
        "2 秒跳出率",
        False,
        {
            "workspace_id": workspace_id,
            "account_id": account_id,
            "platform": "douyin",
            "content_type": "video",
            "maturity_bucket": "24h",
        },
    )

    assert items[0].title == "跳出率样本 0"
    assert "P10" in items[0].reason
    assert items[1].title == "跳出率样本 9"
    assert "P75" in items[1].reason
