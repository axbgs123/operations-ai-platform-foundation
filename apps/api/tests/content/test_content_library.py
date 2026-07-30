from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_session
from app.main import app
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


def create_workspace(
    client: TestClient,
    name: str,
) -> tuple[dict, str]:
    workspace = client.post("/v1/workspaces", json={"name": name}).json()
    login = client.post(
        "/v1/sessions/invite",
        json={
            "code": workspace["admin_code"],
            "display_name": f"{name}管理员",
        },
    ).json()
    return workspace, login["csrf_token"]


def create_account(
    client: TestClient,
    workspace_id: str,
    csrf: str,
    *,
    platform: str,
    name: str,
) -> dict:
    return client.post(
        f"/v1/workspaces/{workspace_id}/accounts",
        headers={"X-CSRF-Token": csrf},
        json={
            "platform": platform,
            "name": name,
            "objectives": ["engagement"],
            "metric_weights": {"likes": 1},
            "benchmark_sample_size": 30,
        },
    ).json()


def create_content(
    client: TestClient,
    workspace_id: str,
    csrf: str,
    account: dict,
    *,
    title: str,
    column_id: str | None = None,
) -> dict:
    return client.post(
        "/v1/contents",
        headers={"X-CSRF-Token": csrf},
        json={
            "workspace_id": workspace_id,
            "account_id": account["id"],
            "platform": account["platform"],
            "content_type": "video",
            "column_campaign_id": column_id,
            "title": title,
            "body": "人工合成正文",
        },
    ).json()


def test_workspace_content_list_filters_and_paginates_stably() -> None:
    with configured_client() as client:
        workspace, csrf = create_workspace(client, "内容库")
        douyin = create_account(
            client,
            workspace["workspace_id"],
            csrf,
            platform="douyin",
            name="抖音账号",
        )
        xiaohongshu = create_account(
            client,
            workspace["workspace_id"],
            csrf,
            platform="xiaohongshu",
            name="小红书账号",
        )
        column = client.post(
            (
                f"/v1/workspaces/{workspace['workspace_id']}/accounts/"
                f"{douyin['id']}/columns-campaigns"
            ),
            headers={"X-CSRF-Token": csrf},
            json={"name": "AI 栏目", "kind": "column"},
        ).json()
        first = create_content(
            client,
            workspace["workspace_id"],
            csrf,
            douyin,
            title="同名 AI 内容",
            column_id=column["id"],
        )
        second = create_content(
            client,
            workspace["workspace_id"],
            csrf,
            douyin,
            title="同名 AI 内容",
            column_id=column["id"],
        )
        create_content(
            client,
            workspace["workspace_id"],
            csrf,
            xiaohongshu,
            title="不应混入的小红书内容",
        )

        response = client.get(
            f"/v1/workspaces/{workspace['workspace_id']}/contents",
            params={
                "platform": "douyin",
                "account_id": douyin["id"],
                "column_id": column["id"],
                "content_type": "video",
                "status": "draft",
                "query": "AI",
                "sort": "title_asc",
                "page": 1,
                "page_size": 1,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 2
        assert payload["page"] == 1
        assert payload["page_size"] == 1
        assert payload["items"][0]["id"] == min(first["id"], second["id"])
        assert payload["items"][0]["platform"] == "douyin"
        assert payload["items"][0]["latest_maturity"] is None
        assert payload["items"][0]["data_completeness"] == 0
        assert payload["items"][0]["analysis_status"] == "not_requested"
        assert payload["items"][0]["risk_status"] == "not_scanned"

        page_two = client.get(
            f"/v1/workspaces/{workspace['workspace_id']}/contents",
            params={
                "platform": "douyin",
                "sort": "title_asc",
                "page": 2,
                "page_size": 1,
            },
        ).json()
        assert page_two["items"][0]["id"] == max(first["id"], second["id"])


def test_content_list_rejects_incompatible_or_cross_workspace_scope() -> None:
    with configured_client() as client:
        workspace_a, csrf_a = create_workspace(client, "工作区 A")
        account_a = create_account(
            client,
            workspace_a["workspace_id"],
            csrf_a,
            platform="douyin",
            name="A 抖音",
        )
        client.post(
            (
                f"/v1/workspaces/{workspace_a['workspace_id']}/accounts/"
                f"{account_a['id']}/columns-campaigns"
            ),
            headers={"X-CSRF-Token": csrf_a},
            json={"name": "A 栏目", "kind": "column"},
        ).json()

        mismatch = client.get(
            f"/v1/workspaces/{workspace_a['workspace_id']}/contents",
            params={
                "platform": "xiaohongshu",
                "account_id": account_a["id"],
            },
        )
        assert mismatch.status_code == 404
        wrong_column = client.get(
            f"/v1/workspaces/{workspace_a['workspace_id']}/contents",
            params={
                "account_id": account_a["id"],
                "column_id": "00000000-0000-0000-0000-000000000001",
            },
        )
        assert wrong_column.status_code == 404

        workspace_b, _ = create_workspace(client, "工作区 B")
        cross_workspace = client.get(
            f"/v1/workspaces/{workspace_a['workspace_id']}/contents",
            params={"account_id": account_a["id"]},
        )
        assert cross_workspace.status_code == 404
        assert workspace_b["workspace_id"] != workspace_a["workspace_id"]


def test_content_list_filters_latest_maturity_and_title_only_for_viewer() -> None:
    with configured_client() as client:
        workspace, csrf = create_workspace(client, "成熟度工作区")
        account = create_account(
            client,
            workspace["workspace_id"],
            csrf,
            platform="douyin",
            name="成熟度账号",
        )
        matching = create_content(
            client,
            workspace["workspace_id"],
            csrf,
            account,
            title="标题命中词",
        )
        body_only = client.post(
            "/v1/contents",
            headers={"X-CSRF-Token": csrf},
            json={
                "workspace_id": workspace["workspace_id"],
                "account_id": account["id"],
                "platform": "douyin",
                "content_type": "video",
                "title": "标题不匹配",
                "body": "正文包含命中词但不得被搜索",
            },
        ).json()
        assert body_only["id"] != matching["id"]
        published = client.patch(
            f"/v1/contents/{matching['id']}",
            headers={"X-CSRF-Token": csrf},
            json={"status": "published"},
        ).json()
        staged = client.post(
            f"/v1/contents/{matching['id']}/snapshots",
            headers={"X-CSRF-Token": csrf},
            json={
                "collected_at": (
                    datetime.fromisoformat(published["published_at"])
                    + timedelta(hours=24)
                ).isoformat(),
                "source": "manual",
                "metrics": [{"key": "views", "raw_value": 100}],
            },
        ).json()
        confirmed = client.post(
            f"/v1/contents/{matching['id']}/snapshots/{staged['id']}/confirm",
            headers={"X-CSRF-Token": csrf},
        )
        assert confirmed.status_code == 200

        listed = client.get(
            f"/v1/workspaces/{workspace['workspace_id']}/contents",
            params={"maturity": "24h", "query": "命中词"},
        )
        assert listed.status_code == 200
        payload = listed.json()
        assert [item["id"] for item in payload["items"]] == [matching["id"]]
        assert payload["items"][0]["latest_maturity"] == "24h"
        assert payload["items"][0]["data_completeness"] > 0

        staged_72h = client.post(
            f"/v1/contents/{matching['id']}/snapshots",
            headers={"X-CSRF-Token": csrf},
            json={
                "collected_at": (
                    datetime.fromisoformat(published["published_at"])
                    + timedelta(hours=72)
                ).isoformat(),
                "source": "manual",
                "metrics": [{"key": "views", "raw_value": 180}],
            },
        ).json()
        confirmed_72h = client.post(
            f"/v1/contents/{matching['id']}/snapshots/{staged_72h['id']}/confirm",
            headers={"X-CSRF-Token": csrf},
        )
        assert confirmed_72h.status_code == 200

        viewer_code = client.post(
            f"/v1/workspaces/{workspace['workspace_id']}/members/codes",
            headers={"X-CSRF-Token": csrf},
            json={"role": "viewer"},
        ).json()["code"]
        client.post(
            "/v1/sessions/invite",
            json={"code": viewer_code, "display_name": "只读成员"},
        )
        drill_down = client.get(
            f"/v1/workspaces/{workspace['workspace_id']}/contents",
            params={
                "platform": "douyin",
                "account_id": account["id"],
                "content_type": "video",
                "maturity": "24h",
                "metric_key": "views",
            },
        )
        assert drill_down.status_code == 200
        assert [
            item["id"] for item in drill_down.json()["items"]
        ] == [matching["id"]]
        incomplete = client.get(
            f"/v1/workspaces/{workspace['workspace_id']}/contents",
            params={"metric_key": "views"},
        )
        assert incomplete.status_code == 422


def test_content_detail_read_model_is_workspace_scoped_and_safe() -> None:
    with configured_client() as client:
        workspace, csrf = create_workspace(client, "详情工作区")
        account = create_account(
            client,
            workspace["workspace_id"],
            csrf,
            platform="douyin",
            name="详情账号",
        )
        content = create_content(
            client,
            workspace["workspace_id"],
            csrf,
            account,
            title="详情内容",
        )
        published = client.patch(
            f"/v1/contents/{content['id']}",
            headers={"X-CSRF-Token": csrf},
            json={"status": "published"},
        )
        assert published.status_code == 200
        snapshot = client.post(
            f"/v1/contents/{content['id']}/snapshots",
            headers={"X-CSRF-Token": csrf},
            json={
                "collected_at": (
                    datetime.fromisoformat(published.json()["published_at"])
                    + timedelta(hours=1)
                ).isoformat(),
                "source": "manual",
                "metrics": [
                    {
                        "key": "views",
                        "raw_value": None,
                        "ocr_confidence": None,
                    }
                ],
            },
        )
        assert snapshot.status_code == 201, snapshot.text

        response = client.get(
            (
                f"/v1/workspaces/{workspace['workspace_id']}/contents/"
                f"{content['id']}/detail"
            )
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["content"]["id"] == content["id"]
        assert payload["lifecycle_stage"] == "数据采集中"
        assert payload["snapshot_trend"]["eligible"] is False
        assert payload["snapshot_trend"]["metric_key"] is None
        assert payload["snapshots"][0]["metrics"][0]["raw_value"] is None
        assert payload["snapshots"][0]["metrics"][0]["normalized_value"] is None
        assert payload["analysis_runs"] == []
        assert payload["risk_scans"] == []
        assert payload["generation_records"] == []
        serialized = response.text.lower()
        for secret_name in (
            "api_key",
            "secret_ciphertext",
            "provider_workspace_id",
            "prompt_text",
        ):
            assert secret_name not in serialized

        other, _ = create_workspace(client, "其他工作区")
        denied = client.get(
            (
                f"/v1/workspaces/{workspace['workspace_id']}/contents/"
                f"{content['id']}/detail"
            )
        )
        assert denied.status_code == 404
        assert other["workspace_id"] != workspace["workspace_id"]


def test_content_list_bounds_page_size() -> None:
    with configured_client() as client:
        workspace, _ = create_workspace(client, "分页工作区")
        response = client.get(
            f"/v1/workspaces/{workspace['workspace_id']}/contents",
            params={"page": 0, "page_size": 201},
        )
        assert response.status_code == 422
