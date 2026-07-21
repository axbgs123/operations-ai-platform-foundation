from collections.abc import Iterator
from contextlib import contextmanager

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
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
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


def create_admin_and_account(client: TestClient) -> tuple[str, str, dict]:
    workspace = client.post("/v1/workspaces", json={"name": "内容工作区"}).json()
    login = client.post(
        "/v1/sessions/invite",
        json={"code": workspace["admin_code"], "display_name": "管理员"},
    ).json()
    csrf = login["csrf_token"]
    account = client.post(
        f"/v1/workspaces/{workspace['workspace_id']}/accounts",
        headers={"X-CSRF-Token": csrf},
        json={
            "platform": "douyin",
            "name": "城市穿搭研究所",
            "objectives": ["engagement", "conversion"],
            "metric_weights": {"likes": 7, "comments": 3},
            "benchmark_sample_size": 30,
        },
    ).json()
    return workspace["workspace_id"], csrf, account


def test_content_lifecycle_freezes_published_copy_and_configuration_versions() -> None:
    with configured_client() as client:
        workspace_id, csrf, account = create_admin_and_account(client)
        headers = {"X-CSRF-Token": csrf}
        mismatch = client.post(
            "/v1/contents",
            headers=headers,
            json={
                "workspace_id": workspace_id,
                "account_id": account["id"],
                "platform": "xiaohongshu",
                "title": "平台不匹配",
                "body": "测试",
            },
        )
        assert mismatch.status_code == 422

        created = client.post(
            "/v1/contents",
            headers=headers,
            json={
                "workspace_id": workspace_id,
                "account_id": account["id"],
                "platform": "douyin",
                "title": "发布前标题",
                "body": "发布前文案",
                "work_url": "https://www.douyin.com/video/example",
            },
        )
        assert created.status_code == 201
        content = created.json()
        content_id = content["id"]
        assert content["status"] == "draft"
        assert content["objective_profile_id"] == account["objective_profile"]["id"]
        assert content["benchmark_profile_id"] == account["benchmark_profile"]["id"]

        other_account = client.post(
            f"/v1/workspaces/{workspace_id}/accounts",
            headers=headers,
            json={
                "platform": "douyin",
                "name": "另一个账号",
                "objectives": ["reach"],
                "metric_weights": {"views": 1},
                "benchmark_sample_size": 30,
            },
        ).json()
        other_column = client.post(
            f"/v1/workspaces/{workspace_id}/accounts/{other_account['id']}/columns-campaigns",
            headers=headers,
            json={"name": "其他账号栏目", "kind": "column"},
        ).json()
        wrong_column = client.patch(
            f"/v1/contents/{content_id}",
            headers=headers,
            json={"column_campaign_id": other_column["id"]},
        )
        assert wrong_column.status_code == 422

        published = client.patch(
            f"/v1/contents/{content_id}",
            headers=headers,
            json={"status": "published"},
        )
        assert published.status_code == 200
        assert published.json()["published_title"] == "发布前标题"

        edited = client.patch(
            f"/v1/contents/{content_id}",
            headers=headers,
            json={"title": "发布后的新草稿", "body": "新草稿文案"},
        )
        assert edited.status_code == 200
        assert edited.json()["title"] == "发布后的新草稿"
        assert edited.json()["published_title"] == "发布前标题"

        assert client.delete(
            f"/v1/contents/{content_id}", headers=headers
        ).status_code == 204
        assert client.get(f"/v1/contents/{content_id}").status_code == 404
        trash = client.get(
            "/v1/contents",
            params={"workspace_id": workspace_id, "trash": True},
        )
        assert [item["id"] for item in trash.json()] == [content_id]

        restored = client.patch(
            f"/v1/contents/{content_id}",
            headers=headers,
            json={"restore": True},
        )
        assert restored.status_code == 200
        assert restored.json()["deleted_at"] is None


def test_viewer_cannot_modify_content() -> None:
    with configured_client() as client:
        workspace_id, admin_csrf, account = create_admin_and_account(client)
        viewer_code = client.post(
            f"/v1/workspaces/{workspace_id}/members/codes",
            headers={"X-CSRF-Token": admin_csrf},
            json={"role": "viewer"},
        ).json()["code"]
        viewer = client.post(
            "/v1/sessions/invite",
            json={"code": viewer_code, "display_name": "查看者"},
        ).json()
        response = client.post(
            "/v1/contents",
            headers={"X-CSRF-Token": viewer["csrf_token"]},
            json={
                "workspace_id": workspace_id,
                "account_id": account["id"],
                "platform": "douyin",
                "title": "越权创建",
                "body": "不允许",
            },
        )
        assert response.status_code == 403
