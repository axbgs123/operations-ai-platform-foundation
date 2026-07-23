from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.imports.extension_auth import (
    ExtensionToken,
    ExtensionTokenScope,
    ExtensionTokenService,
)
from tests.imports.helpers import configured_client


def _bind(client: TestClient, invite_code: str, client_id: str = "test-extension"):
    return client.post(
        "/v1/extension/bind",
        json={"invite_code": invite_code, "client_id": client_id},
        headers={
            "Idempotency-Key": f"bind-{client_id}",
            "X-Extension-Client": client_id,
        },
    )


def test_binding_returns_short_lived_scoped_token_without_persisting_secrets() -> None:
    with configured_client() as (client, engine):
        workspace = client.post("/v1/workspaces", json={"name": "扩展合成工作区"}).json()
        invite_code = workspace["admin_code"]

        response = _bind(client, invite_code)

        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["token_type"] == "Bearer"
        assert payload["workspace_id"] == workspace["workspace_id"]
        assert payload["scopes"] == [
            ExtensionTokenScope.CAPTURE_CREATE.value,
            ExtensionTokenScope.CAPTURE_UPLOAD.value,
            ExtensionTokenScope.CAPTURE_READ.value,
        ]
        assert invite_code not in response.text
        assert payload["expires_at"] > payload["issued_at"]

        with Session(engine) as session:
            stored = session.scalar(select(ExtensionToken))
        assert stored is not None
        assert invite_code not in str(stored)
        assert stored.token_hash != payload["access_token"]
        assert len(stored.token_hash) == 64


def test_token_auth_uses_bearer_header_and_rejects_expired_revoked_or_wrong_scope() -> None:
    with configured_client() as (client, engine):
        workspace = client.post("/v1/workspaces", json={"name": "令牌生命周期"}).json()
        response = _bind(client, workspace["admin_code"])
        token = response.json()["access_token"]
        session = Session(engine, expire_on_commit=False)
        service = ExtensionTokenService(session)

        authenticated = service.authenticate(
            token,
            required_scope=ExtensionTokenScope.CAPTURE_READ,
        )
        assert authenticated is not None
        assert authenticated.workspace_id == UUID(workspace["workspace_id"])

        assert (
            service.authenticate(
                token,
                required_scope=ExtensionTokenScope.CONFIRM_SNAPSHOT,
            )
            is None
        )
        service.revoke(authenticated.token_id)
        session.commit()
        assert service.authenticate(token) is None

        issued_at = datetime.now(UTC) - timedelta(hours=2)
        expired = service.issue(
            workspace_id=authenticated.workspace_id,
            member_id=authenticated.member_id,
            client_id="expired-client",
            now=issued_at,
            lifetime=timedelta(minutes=1),
        )
        assert service.authenticate(expired.access_token, now=issued_at + timedelta(minutes=2)) is None
        session.close()

        assert client.get(
            "/v1/extension/tasks/not-a-real-task",
            params={"access_token": token},
        ).status_code in {401, 403, 404}


def test_viewer_binding_is_allowed_but_never_grants_formal_write_scope() -> None:
    with configured_client() as (client, _):
        workspace = client.post("/v1/workspaces", json={"name": "查看者扩展"}).json()
        login = client.post(
            "/v1/sessions/invite",
            json={"code": workspace["admin_code"], "display_name": "管理员"},
        ).json()
        viewer_code = client.post(
            f"/v1/workspaces/{workspace['workspace_id']}/members/codes",
            headers={"X-CSRF-Token": login["csrf_token"]},
            json={"role": "viewer"},
        ).json()["code"]

        response = _bind(client, viewer_code, "viewer-extension")

        assert response.status_code == 201, response.text
        assert "confirm_snapshot" not in response.json()["scopes"]
        assert "manage_members" not in response.json()["scopes"]


def test_binding_is_idempotency_protected_and_bearer_only_with_redacted_errors() -> None:
    with configured_client() as (client, engine):
        workspace = client.post("/v1/workspaces", json={"name": "扩展安全接口"}).json()
        other_workspace = client.post(
            "/v1/workspaces", json={"name": "其他扩展工作区"}
        ).json()
        first = _bind(client, workspace["admin_code"], "secure-extension")
        assert first.status_code == 201
        token = first.json()["access_token"]

        duplicate = _bind(client, workspace["admin_code"], "secure-extension")
        assert duplicate.status_code == 409
        assert workspace["admin_code"] not in duplicate.text
        assert token not in duplicate.text

        query_only = client.get(
            "/v1/extension/binding",
            params={"access_token": token},
        )
        assert query_only.status_code == 401
        assert token not in query_only.text

        readable = client.get(
            "/v1/extension/binding",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert readable.status_code == 200
        assert readable.json()["workspace_id"] == workspace["workspace_id"]
        assert token not in readable.text
        assert client.get(
            (
                f"/v1/extension/workspaces/"
                f"{other_workspace['workspace_id']}/binding"
            ),
            headers={"Authorization": f"Bearer {token}"},
        ).status_code == 404

        with Session(engine) as session:
            record = session.scalar(select(ExtensionToken))
            assert record is not None
            record.scopes = []
            session.commit()
        assert client.get(
            "/v1/extension/binding",
            headers={"Authorization": f"Bearer {token}"},
        ).status_code == 403

        revoked = client.delete(
            "/v1/extension/binding",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert revoked.status_code == 204
        assert client.get(
            "/v1/extension/binding",
            headers={"Authorization": f"Bearer {token}"},
        ).status_code == 401
