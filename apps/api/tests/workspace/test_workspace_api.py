from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

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


def create_and_login_admin(client: TestClient) -> tuple[str, str]:
    workspace_response = client.post(
        "/v1/workspaces",
        json={"name": "API 工作区"},
    )
    admin_code = workspace_response.json()["admin_code"]
    login_response = client.post(
        "/v1/sessions/invite",
        json={"code": admin_code, "display_name": "管理员"},
    )
    return workspace_response.json()["workspace_id"], login_response.json()[
        "csrf_token"
    ]


def test_invite_login_sets_http_only_cookie_and_logout_requires_csrf() -> None:
    with configured_client() as client:
        workspace_response = client.post(
            "/v1/workspaces",
            json={"name": "API 工作区"},
        )
        assert workspace_response.status_code == 201
        admin_code = workspace_response.json()["admin_code"]

        login_response = client.post(
            "/v1/sessions/invite",
            json={"code": admin_code, "display_name": "管理员"},
        )
        assert login_response.status_code == 201
        csrf_token = login_response.json()["csrf_token"]
        cookie = login_response.headers["set-cookie"].lower()
        assert "session=" in cookie
        assert "httponly" in cookie
        assert "samesite=lax" in cookie
        assert "max-age=" in cookie
        assert "secure" not in cookie

        assert client.delete("/v1/sessions/current").status_code == 403
        logout_response = client.delete(
            "/v1/sessions/current",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert logout_response.status_code == 204


def test_member_code_and_role_changes_require_admin_csrf_and_workspace_scope() -> None:
    with configured_client() as admin_client:
        workspace_id, admin_csrf = create_and_login_admin(admin_client)

        assert (
            admin_client.post(
                f"/v1/workspaces/{workspace_id}/members/codes",
                json={"role": "viewer"},
            ).status_code
            == 403
        )
        code_response = admin_client.post(
            f"/v1/workspaces/{workspace_id}/members/codes",
            json={"role": "viewer"},
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert code_response.status_code == 201

        with TestClient(app) as viewer_client:
            viewer_login = viewer_client.post(
                "/v1/sessions/invite",
                json={
                    "code": code_response.json()["code"],
                    "display_name": "查看者",
                },
            )
            viewer_id = viewer_login.json()["member_id"]
            viewer_csrf = viewer_login.json()["csrf_token"]
            viewer_session = viewer_client.cookies.get("session")
            assert (
                viewer_client.post(
                    f"/v1/workspaces/{workspace_id}/members/codes",
                    json={"role": "editor"},
                    headers={"X-CSRF-Token": viewer_csrf},
                ).status_code
                == 403
            )

        update_response = admin_client.patch(
            f"/v1/workspaces/{workspace_id}/members/{viewer_id}",
            json={"role": "editor"},
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert update_response.status_code == 200
        assert update_response.json()["role"] == "editor"

        cross_workspace = admin_client.patch(
            f"/v1/workspaces/{uuid4()}/members/{viewer_id}",
            json={"role": "viewer"},
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert cross_workspace.status_code == 404

        revoke_response = admin_client.patch(
            f"/v1/workspaces/{workspace_id}/members/{viewer_id}",
            json={"revoked": True},
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert revoke_response.status_code == 200
        assert revoke_response.json()["revoked_at"] is not None

        with TestClient(app) as revoked_client:
            revoked_client.cookies.set("session", viewer_session)
            revoked_request = revoked_client.post(
                f"/v1/workspaces/{workspace_id}/members/codes",
                json={"role": "viewer"},
                headers={"X-CSRF-Token": viewer_csrf},
            )
            assert revoked_request.status_code == 401


def test_invite_rate_limit_is_shared_across_requests() -> None:
    with configured_client() as client:
        for attempt in range(10):
            response = client.post(
                "/v1/sessions/invite",
                json={"code": f"invalid-{attempt}", "display_name": "测试"},
            )
            assert response.status_code == 401

        limited = client.post(
            "/v1/sessions/invite",
            json={"code": "invalid-final", "display_name": "测试"},
        )
        assert limited.status_code == 429


def test_local_web_origin_can_use_cookie_authenticated_api() -> None:
    with configured_client() as client:
        response = client.options(
            "/v1/sessions/invite",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == (
            "http://localhost:3000"
        )
        assert response.headers["access-control-allow-credentials"] == "true"
