from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_session
from app.main import app
from app.modules.content.account_service import AccountConfigurationService
from app.modules.workspace.router import invite_attempts


@contextmanager
def configured_client() -> Iterator[TestClient]:
    invite_attempts.clear()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)

    def override_session() -> Iterator[Session]:
        with Session(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def create_admin(client: TestClient, name: str = "账号配置工作区") -> tuple[str, str]:
    workspace = client.post("/v1/workspaces", json={"name": name}).json()
    login = client.post(
        "/v1/sessions/invite",
        json={"code": workspace["admin_code"], "display_name": "管理员"},
    ).json()
    return workspace["workspace_id"], login["csrf_token"]


def test_normalized_weights_sum_to_exactly_one() -> None:
    normalized = AccountConfigurationService.normalize_weights(
        {"views": 1, "likes": 1, "comments": 1}
    )

    assert sum(normalized.values()) == 1


def test_account_configuration_is_versioned_and_weights_are_normalized() -> None:
    with configured_client() as client:
        workspace_id, csrf = create_admin(client)
        headers = {"X-CSRF-Token": csrf}

        invalid = client.post(
            f"/v1/workspaces/{workspace_id}/accounts",
            headers=headers,
            json={
                "platform": "bilibili",
                "name": "非法平台",
                "objectives": ["engagement"],
                "metric_weights": {"likes": 1},
                "benchmark_sample_size": 30,
            },
        )
        assert invalid.status_code == 422

        created = client.post(
            f"/v1/workspaces/{workspace_id}/accounts",
            headers=headers,
            json={
                "platform": "douyin",
                "name": "城市穿搭研究所",
                "objectives": ["engagement", "conversion", "reach"],
                "metric_weights": {"likes": 7, "comments": 3},
                "benchmark_sample_size": 30,
            },
        )
        assert created.status_code == 201
        account = created.json()
        first_objective_id = account["objective_profile"]["id"]
        first_benchmark_id = account["benchmark_profile"]["id"]
        assert account["objective_profile"]["version"] == 1
        assert account["objective_profile"]["objectives"] == [
            "engagement",
            "conversion",
            "reach",
        ]
        assert account["objective_profile"]["metric_weights"] == {
            "likes": 0.7,
            "comments": 0.3,
        }

        updated = client.patch(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/configuration",
            headers=headers,
            json={
                "objectives": ["conversion", "engagement"],
                "metric_weights": {"likes": 1, "comments": 1},
                "benchmark_sample_size": 20,
            },
        )
        assert updated.status_code == 200
        assert updated.json()["objective_profile"]["version"] == 2
        assert updated.json()["objective_profile"]["id"] != first_objective_id
        assert updated.json()["benchmark_profile"]["id"] != first_benchmark_id

        history = client.get(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/configuration/versions",
            headers=headers,
        )
        assert history.status_code == 200
        assert [item["version"] for item in history.json()["objectives"]] == [1, 2]
        assert history.json()["objectives"][0]["id"] == first_objective_id


def test_campaign_override_expires_then_restores_account_versions_and_scope() -> None:
    with configured_client() as client:
        workspace_id, csrf = create_admin(client)
        headers = {"X-CSRF-Token": csrf}
        account_response = client.post(
            f"/v1/workspaces/{workspace_id}/accounts",
            headers=headers,
            json={
                "platform": "xiaohongshu",
                "name": "通勤灵感簿",
                "objectives": ["saves", "engagement"],
                "metric_weights": {"saves": 6, "likes": 4},
                "benchmark_sample_size": 30,
            },
        )
        assert account_response.status_code == 201
        account = account_response.json()

        campaign = client.post(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/columns-campaigns",
            headers=headers,
            json={
                "name": "七夕礼赠活动",
                "kind": "campaign",
                "starts_at": "2026-08-01T00:00:00Z",
                "ends_at": "2026-08-10T23:59:59Z",
                "objectives": ["conversion", "reach"],
                "metric_weights": {"orders": 8, "likes": 2},
                "benchmark_sample_size": 10,
            },
        )
        assert campaign.status_code == 201
        campaign_id = campaign.json()["id"]

        active = client.get(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/effective-configuration",
            params={"column_campaign_id": campaign_id, "at": "2026-08-05T12:00:00Z"},
            headers=headers,
        ).json()
        assert active["source"] == "campaign_override"
        assert active["objective_profile"]["objectives"] == ["conversion", "reach"]

        expired = client.get(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/effective-configuration",
            params={"column_campaign_id": campaign_id, "at": "2026-08-11T12:00:00Z"},
            headers=headers,
        ).json()
        assert expired["source"] == "account_default"
        assert expired["objective_profile"]["id"] == account["objective_profile"]["id"]
        assert expired["benchmark_profile"]["id"] == account["benchmark_profile"]["id"]

        other_workspace_id, other_csrf = create_admin(client, "另一个工作区")
        cross_scope = client.get(
            f"/v1/workspaces/{other_workspace_id}/accounts/{account['id']}/effective-configuration",
            headers={"X-CSRF-Token": other_csrf},
            params={
                "column_campaign_id": campaign_id,
                "at": datetime.now(UTC).isoformat(),
            },
        )
        assert cross_scope.status_code == 404


def test_account_and_campaign_crud_restore_defaults_and_reject_viewer_writes() -> None:
    with configured_client() as client:
        workspace_id, csrf = create_admin(client)
        headers = {"X-CSRF-Token": csrf}
        account = client.post(
            f"/v1/workspaces/{workspace_id}/accounts",
            headers=headers,
            json={
                "platform": "douyin",
                "name": "待修改账号",
                "objectives": ["reach"],
                "metric_weights": {"views": 1},
                "benchmark_sample_size": 30,
            },
        ).json()
        account_id = account["id"]

        listed = client.get(f"/v1/workspaces/{workspace_id}/accounts")
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [account_id]

        renamed = client.patch(
            f"/v1/workspaces/{workspace_id}/accounts/{account_id}",
            headers=headers,
            json={"name": "已修改账号"},
        )
        assert renamed.status_code == 200
        assert renamed.json()["name"] == "已修改账号"

        campaign = client.post(
            f"/v1/workspaces/{workspace_id}/accounts/{account_id}/columns-campaigns",
            headers=headers,
            json={
                "name": "临时冲刺",
                "kind": "campaign",
                "objectives": ["conversion"],
                "metric_weights": {"orders": 1},
                "benchmark_sample_size": 10,
            },
        ).json()
        campaign_id = campaign["id"]
        campaigns = client.get(
            f"/v1/workspaces/{workspace_id}/accounts/{account_id}/columns-campaigns"
        )
        assert [item["id"] for item in campaigns.json()] == [campaign_id]

        restored = client.patch(
            f"/v1/workspaces/{workspace_id}/accounts/{account_id}/columns-campaigns/{campaign_id}",
            headers=headers,
            json={"restore_account_defaults": True},
        )
        assert restored.status_code == 200
        assert restored.json()["objective_profile_id"] is None
        effective = client.get(
            f"/v1/workspaces/{workspace_id}/accounts/{account_id}/effective-configuration",
            params={"column_campaign_id": campaign_id},
        )
        assert effective.json()["source"] == "account_default"

        assert client.delete(
            f"/v1/workspaces/{workspace_id}/accounts/{account_id}/columns-campaigns/{campaign_id}",
            headers=headers,
        ).status_code == 204
        assert client.delete(
            f"/v1/workspaces/{workspace_id}/accounts/{account_id}",
            headers=headers,
        ).status_code == 204
        assert client.get(f"/v1/workspaces/{workspace_id}/accounts").json() == []

        viewer_code = client.post(
            f"/v1/workspaces/{workspace_id}/members/codes",
            headers=headers,
            json={"role": "viewer"},
        ).json()["code"]
        viewer_login = client.post(
            "/v1/sessions/invite",
            json={"code": viewer_code, "display_name": "查看者"},
        ).json()
        forbidden = client.post(
            f"/v1/workspaces/{workspace_id}/accounts",
            headers={"X-CSRF-Token": viewer_login["csrf_token"]},
            json={
                "platform": "douyin",
                "name": "越权创建",
                "objectives": ["reach"],
                "metric_weights": {"views": 1},
                "benchmark_sample_size": 30,
            },
        )
        assert forbidden.status_code == 403
