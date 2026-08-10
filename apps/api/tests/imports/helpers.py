from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_session
from app.main import app
from app.modules.imports.extension_router import binding_attempts, pairing_attempts
from app.modules.imports.capture_service import reset_capture_objects
from app.modules.workspace.router import invite_attempts


@contextmanager
def configured_client() -> Iterator[tuple[TestClient, object]]:
    invite_attempts.clear()
    binding_attempts.clear()
    pairing_attempts.clear()
    reset_capture_objects()
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
            yield client, engine
    finally:
        app.dependency_overrides.clear()
        reset_capture_objects()


def create_workspace_account(
    client: TestClient,
    *,
    workspace_name: str = "合成导入工作区",
    platform: str = "douyin",
) -> tuple[str, str, dict]:
    workspace = client.post("/v1/workspaces", json={"name": workspace_name}).json()
    login = client.post(
        "/v1/sessions/invite",
        json={"code": workspace["admin_code"], "display_name": "导入管理员"},
    ).json()
    workspace_id = workspace["workspace_id"]
    csrf = login["csrf_token"]
    account = client.post(
        f"/v1/workspaces/{workspace_id}/accounts",
        headers={"X-CSRF-Token": csrf},
        json={
            "platform": platform,
            "name": f"{platform} 合成测试账号",
            "objectives": ["reach"],
            "metric_weights": {"views": 1},
            "benchmark_sample_size": 30,
        },
    ).json()
    return workspace_id, csrf, account


def preview_manual(
    client: TestClient,
    *,
    workspace_id: str,
    csrf: str,
    account_id: str,
    platform: str = "douyin",
    content_type: str = "video",
    rows: list[dict],
) -> dict:
    response = client.post(
        f"/v1/workspaces/{workspace_id}/imports/manual/preview",
        headers={"X-CSRF-Token": csrf},
        json={
            "account_id": account_id,
            "platform": platform,
            "content_type": content_type,
            "rows": rows,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_published_content(
    client: TestClient,
    *,
    workspace_id: str,
    csrf: str,
    account: dict,
    title: str,
    work_url: str | None,
) -> dict:
    payload = {
        "workspace_id": workspace_id,
        "account_id": account["id"],
        "platform": account["platform"],
        "content_type": "video",
        "title": title,
        "body": "合成测试内容",
    }
    if work_url is not None:
        payload["work_url"] = work_url
    created = client.post(
        "/v1/contents",
        headers={"X-CSRF-Token": csrf},
        json=payload,
    ).json()
    return client.patch(
        f"/v1/contents/{created['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"status": "published"},
    ).json()


def ids(values: list[str]) -> set[UUID]:
    return {UUID(value) for value in values}
