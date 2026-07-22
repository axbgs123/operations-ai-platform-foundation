from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import app
from app.modules.content.account_models import Platform
from app.modules.metrics.models import (
    ContentType,
    MetricAggregation,
    MetricDefinition,
    MetricUnit,
)
from app.modules.workspace.models import AuditLog
from tests.imports.helpers import configured_client


def test_threshold_configuration_allows_browser_put_preflight() -> None:
    with configured_client() as (client, _):
        response = client.options(
            "/v1/workspaces/00000000-0000-0000-0000-000000000001/accounts/"
            "00000000-0000-0000-0000-000000000002/viral-thresholds",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "content-type,x-csrf-token",
            },
        )

        assert response.status_code == 200
        assert "PUT" in response.headers["access-control-allow-methods"]


def test_only_administrators_can_change_viral_threshold_policy() -> None:
    with configured_client() as (admin, _):
        workspace_id, admin_csrf, account = create_account(admin)
        path = (
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}"
            "/viral-thresholds"
        )
        for role in ("editor", "viewer"):
            code = admin.post(
                f"/v1/workspaces/{workspace_id}/members/codes",
                headers={"X-CSRF-Token": admin_csrf},
                json={"role": role},
            )
            assert code.status_code == 201, code.text
            with TestClient(app) as member:
                login = member.post(
                    "/v1/sessions/invite",
                    json={
                        "code": code.json()["code"],
                        "display_name": f"{role} 测试成员",
                    },
                )
                response = member.put(
                    path,
                    headers={"X-CSRF-Token": login.json()["csrf_token"]},
                    json={
                        "rules": [
                            {
                                "category": "traffic",
                                "metric_key": "views",
                                "minimum_value": 100,
                            }
                        ]
                    },
                )
                assert response.status_code == 403


def create_account(client: TestClient) -> tuple[str, str, dict]:
    workspace = client.post(
        "/v1/workspaces", json={"name": "合成爆款工作区"}
    ).json()
    login = client.post(
        "/v1/sessions/invite",
        json={"code": workspace["admin_code"], "display_name": "爆款管理员"},
    ).json()
    workspace_id = workspace["workspace_id"]
    account = client.post(
        f"/v1/workspaces/{workspace_id}/accounts",
        headers={"X-CSRF-Token": login["csrf_token"]},
        json={
            "platform": "douyin",
            "name": "合成抖音账号",
            "objectives": ["reach", "engagement", "growth", "conversion"],
            "metric_weights": {
                "views": 0.4,
                "likes": 0.2,
                "followers_gained": 0.2,
                "profile_visits": 0.2,
            },
            "benchmark_sample_size": 30,
        },
    ).json()
    return workspace_id, login["csrf_token"], account


def add_sample(
    client: TestClient,
    *,
    workspace_id: str,
    csrf: str,
    account: dict,
    index: int,
) -> dict:
    content = client.post(
        "/v1/contents",
        headers={"X-CSRF-Token": csrf},
        json={
            "workspace_id": workspace_id,
            "account_id": account["id"],
            "platform": "douyin",
            "content_type": "video",
            "title": f"合成爆款内容 {index}",
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
                {"key": "views", "raw_value": (index + 1) * 100},
                {"key": "likes", "raw_value": (index + 1) * 10},
                {"key": "followers_gained", "raw_value": index + 1},
                {"key": "profile_visits", "raw_value": (index + 1) * 5},
            ],
        },
    ).json()
    confirmed = client.post(
        f"/v1/contents/{content['id']}/snapshots/{snapshot['id']}/confirm",
        headers={"X-CSRF-Token": csrf},
    )
    assert confirmed.status_code == 200, confirmed.text
    return content


def configure_threshold(
    client: TestClient,
    *,
    workspace_id: str,
    account_id: str,
    csrf: str,
    minimum_value: int,
) -> dict:
    response = client.put(
        f"/v1/workspaces/{workspace_id}/accounts/{account_id}/viral-thresholds",
        headers={"X-CSRF-Token": csrf},
        json={
            "rules": [
                {
                    "category": "traffic",
                    "metric_key": "views",
                    "minimum_value": minimum_value,
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def evaluate_candidates(
    client: TestClient,
    *,
    workspace_id: str,
    account_id: str,
    csrf: str,
) -> list[dict]:
    response = client.post(
        f"/v1/workspaces/{workspace_id}/accounts/{account_id}"
        "/viral-candidates/evaluate",
        headers={"X-CSRF-Token": csrf},
        json={"content_type": "video", "maturity_bucket": "24h"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_candidate_requires_ten_samples_top_decile_and_absolute_threshold() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = create_account(client)
        threshold_path = (
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}"
            "/viral-thresholds"
        )
        assert client.get(threshold_path).json() is None
        threshold_v1 = configure_threshold(
            client,
            workspace_id=workspace_id,
            account_id=account["id"],
            csrf=csrf,
            minimum_value=950,
        )
        assert threshold_v1["version"] == 1
        assert threshold_v1["objective_profile_id"] == account["objective_profile"]["id"]
        assert threshold_v1["benchmark_profile_id"] == account["benchmark_profile"]["id"]
        assert client.get(threshold_path).json() == threshold_v1

        updated_configuration = client.patch(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/configuration",
            headers={"X-CSRF-Token": csrf},
            json={
                "objectives": ["reach", "engagement", "growth", "conversion"],
                "metric_weights": {
                    "views": 0.4,
                    "likes": 0.2,
                    "followers_gained": 0.2,
                    "profile_visits": 0.2,
                },
                "benchmark_sample_size": 10,
            },
        )
        assert updated_configuration.status_code == 200
        assert (
            updated_configuration.json()["benchmark_profile"]["id"]
            != threshold_v1["benchmark_profile_id"]
        )

        for index in range(9):
            add_sample(
                client,
                workspace_id=workspace_id,
                csrf=csrf,
                account=account,
                index=index,
            )
        assert evaluate_candidates(
            client,
            workspace_id=workspace_id,
            account_id=account["id"],
            csrf=csrf,
        ) == []

        top_content = add_sample(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            index=9,
        )
        candidates = evaluate_candidates(
            client,
            workspace_id=workspace_id,
            account_id=account["id"],
            csrf=csrf,
        )
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate["content_id"] == top_content["id"]
        assert candidate["category"] == "traffic"
        assert candidate["metric_key"] == "views"
        assert candidate["actual_value"] == 1000
        assert candidate["percentile"] >= 0.9
        assert candidate["sample_count"] == 10
        assert candidate["threshold_value"] == 950
        assert candidate["threshold_profile_version"] == 1
        assert candidate["objective_profile_id"]
        assert candidate["benchmark_profile_id"]
        assert candidate["objective_profile_id"] == threshold_v1["objective_profile_id"]
        assert candidate["benchmark_profile_id"] == threshold_v1["benchmark_profile_id"]
        assert candidate["platform"] == "douyin"
        assert candidate["content_type"] == "video"
        assert candidate["maturity_bucket"] == "24h"
        assert candidate["threshold_profile_id"] == threshold_v1["id"]
        assert len(candidate["sample_snapshot_ids"]) == 10
        assert candidate["comparison_started_at"]
        assert candidate["comparison_ended_at"]
        assert candidate["reason"]

        threshold_v2 = configure_threshold(
            client,
            workspace_id=workspace_id,
            account_id=account["id"],
            csrf=csrf,
            minimum_value=1001,
        )
        assert threshold_v2["version"] == 2
        assert evaluate_candidates(
            client,
            workspace_id=workspace_id,
            account_id=account["id"],
            csrf=csrf,
        ) == []

        history = client.get(
            f"/v1/workspaces/{workspace_id}/viral-candidates",
            params={"account_id": account["id"]},
        )
        assert history.status_code == 200, history.text
        assert len(history.json()) == 1
        assert history.json()[0]["threshold_profile_version"] == 1
        assert history.json()[0]["threshold_value"] == 950


def test_threshold_rules_reject_wrong_category_and_lower_is_better_metrics() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_account(client)
        path = (
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}"
            "/viral-thresholds"
        )
        wrong_category = client.put(
            path,
            headers={"X-CSRF-Token": csrf},
            json={
                "rules": [
                    {
                        "category": "conversion",
                        "metric_key": "views",
                        "minimum_value": 100,
                    }
                ]
            },
        )
        assert wrong_category.status_code == 422

        lower_is_better = client.put(
            path,
            headers={"X-CSRF-Token": csrf},
            json={
                "rules": [
                    {
                        "category": "traffic",
                        "metric_key": "bounce_rate_2s",
                        "minimum_value": 0,
                    }
                ]
            },
        )
        assert lower_is_better.status_code == 422

        with Session(engine) as session:
            session.add(
                MetricDefinition(
                    workspace_id=UUID(workspace_id),
                    platform=Platform.DOUYIN,
                    content_type=ContentType.VIDEO,
                    key="qualified_leads",
                    label="有效线索",
                    unit=MetricUnit.COUNT,
                    aggregation=MetricAggregation.LATEST,
                    higher_is_better=True,
                    is_default=False,
                )
            )
            session.commit()
        custom_metric = client.put(
            path,
            headers={"X-CSRF-Token": csrf},
            json={
                "rules": [
                    {
                        "category": "conversion",
                        "metric_key": "qualified_leads",
                        "minimum_value": 10,
                    }
                ]
            },
        )
        assert custom_metric.status_code == 200, custom_metric.text


def test_candidate_categories_cover_traffic_engagement_growth_and_conversion() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = create_account(client)
        response = client.put(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}"
            "/viral-thresholds",
            headers={"X-CSRF-Token": csrf},
            json={
                "rules": [
                    {
                        "category": "traffic",
                        "metric_key": "views",
                        "minimum_value": 950,
                    },
                    {
                        "category": "engagement",
                        "metric_key": "likes",
                        "minimum_value": 95,
                    },
                    {
                        "category": "growth",
                        "metric_key": "followers_gained",
                        "minimum_value": 9,
                    },
                    {
                        "category": "conversion",
                        "metric_key": "profile_visits",
                        "minimum_value": 45,
                    },
                ]
            },
        )
        assert response.status_code == 200, response.text
        for index in range(10):
            add_sample(
                client,
                workspace_id=workspace_id,
                csrf=csrf,
                account=account,
                index=index,
            )

        candidates = evaluate_candidates(
            client,
            workspace_id=workspace_id,
            account_id=account["id"],
            csrf=csrf,
        )

        assert {candidate["category"] for candidate in candidates} == {
            "traffic",
            "engagement",
            "growth",
            "conversion",
        }


def test_library_requires_manual_metadata_and_revoke_preserves_audit() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_account(client)
        configure_threshold(
            client,
            workspace_id=workspace_id,
            account_id=account["id"],
            csrf=csrf,
            minimum_value=950,
        )
        for index in range(10):
            add_sample(
                client,
                workspace_id=workspace_id,
                csrf=csrf,
                account=account,
                index=index,
            )
        candidate = evaluate_candidates(
            client,
            workspace_id=workspace_id,
            account_id=account["id"],
            csrf=csrf,
        )[0]
        generation_path = (
            f"/v1/workspaces/{workspace_id}/viral-library/generation-sources"
        )
        assert client.get(
            generation_path, params={"account_id": account["id"]}
        ).json() == []

        invalid = client.post(
            f"/v1/workspaces/{workspace_id}/viral-candidates/{candidate['id']}/confirm",
            headers={"X-CSRF-Token": csrf},
            json={
                "strategy_tags": ["   "],
                "applicable_scenarios": ["   "],
                "structure_summary": "   ",
            },
        )
        assert invalid.status_code == 422

        confirmed = client.post(
            f"/v1/workspaces/{workspace_id}/viral-candidates/{candidate['id']}/confirm",
            headers={"X-CSRF-Token": csrf},
            json={
                "strategy_tags": ["强钩子", "结果前置"],
                "applicable_scenarios": ["新品讲解", "教程"],
                "structure_summary": "痛点开场—方法拆解—结果证明—行动引导",
            },
        )
        assert confirmed.status_code == 201, confirmed.text
        item = confirmed.json()
        assert item["candidate_id"] == candidate["id"]
        assert item["active"] is True
        assert item["generation_eligible"] is True
        assert item["strategy_tags"] == ["强钩子", "结果前置"]
        assert item["applicable_scenarios"] == ["新品讲解", "教程"]
        assert item["confirmed_by"]

        generation_sources = client.get(
            generation_path, params={"account_id": account["id"]}
        )
        assert generation_sources.status_code == 200, generation_sources.text
        assert [source["id"] for source in generation_sources.json()] == [item["id"]]

        other_account = client.post(
            f"/v1/workspaces/{workspace_id}/accounts",
            headers={"X-CSRF-Token": csrf},
            json={
                "platform": "douyin",
                "name": "隔离验证账号",
                "objectives": ["reach"],
                "metric_weights": {"views": 1},
                "benchmark_sample_size": 30,
            },
        )
        assert other_account.status_code == 201, other_account.text
        assert client.get(
            generation_path,
            params={"account_id": other_account.json()["id"]},
        ).json() == []

        deleted = client.delete(
            f"/v1/contents/{candidate['content_id']}",
            headers={"X-CSRF-Token": csrf},
        )
        assert deleted.status_code == 204, deleted.text
        assert client.get(
            generation_path, params={"account_id": account["id"]}
        ).json() == []
        deleted_history = client.get(
            f"/v1/workspaces/{workspace_id}/viral-library",
            params={"account_id": account["id"]},
        ).json()
        assert deleted_history[0]["active"] is True
        assert deleted_history[0]["generation_eligible"] is False

        invalid_revoke = client.post(
            f"/v1/workspaces/{workspace_id}/viral-library/{item['id']}/revoke",
            headers={"X-CSRF-Token": csrf},
            json={"reason": "   "},
        )
        assert invalid_revoke.status_code == 422

        revoked = client.post(
            f"/v1/workspaces/{workspace_id}/viral-library/{item['id']}/revoke",
            headers={"X-CSRF-Token": csrf},
            json={"reason": "策略已经不再适用"},
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["active"] is False
        assert revoked.json()["revoked_at"]
        assert revoked.json()["revoked_by"]
        assert revoked.json()["revocation_reason"] == "策略已经不再适用"
        assert client.get(
            generation_path, params={"account_id": account["id"]}
        ).json() == []

        history = client.get(
            f"/v1/workspaces/{workspace_id}/viral-library",
            params={"account_id": account["id"]},
        )
        assert history.status_code == 200, history.text
        assert len(history.json()) == 1
        assert history.json()[0]["id"] == item["id"]
        assert history.json()[0]["active"] is False

        with Session(engine) as session:
            actions = set(
                session.scalars(
                    select(AuditLog.action).where(
                            AuditLog.workspace_id == UUID(workspace_id)
                    )
                )
            )
        assert "viral_library.confirmed" in actions
        assert "viral_library.revoked" in actions
