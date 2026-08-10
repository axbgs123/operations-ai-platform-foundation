import base64
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rate_limit import RateLimitCategory, category_for_request
from app.main import app
from app.modules.imports.models import ExtensionDeviceBinding
from app.modules.workspace.models import WorkspaceMember
from tests.imports.helpers import configured_client
from tests.imports.test_extension_devices import p256_fixture, sign_raw_p256


CLIENT_ID = "operations-capture-extension"


def _create_workspace_session(client: TestClient) -> tuple[dict, dict]:
    workspace = client.post("/v1/workspaces", json={"name": "设备 API 工作区"}).json()
    login = client.post(
        "/v1/sessions/invite",
        json={"code": workspace["admin_code"], "display_name": "设备管理员"},
    )
    assert login.status_code == 201, login.text
    return workspace, login.json()


def _public_key() -> tuple[object, dict[str, str]]:
    return p256_fixture()


def _pair_real_device(
    client: TestClient, workspace: dict, login: dict
) -> tuple[dict, object]:
    code = client.post(
        f"/v1/workspaces/{workspace['workspace_id']}/extension-pairing-codes",
        headers={"X-CSRF-Token": login["csrf_token"]},
    )
    assert code.status_code == 201, code.text
    private_key, public_key = _public_key()
    response = client.post(
        "/v1/extension/pair",
        headers={"X-Extension-Client": CLIENT_ID},
        json={
            "pairing_code": code.json()["pairing_code"],
            "client_id": CLIENT_ID,
            "device_id": str(uuid4()),
            "device_public_key_jwk": public_key,
            "device_label": "Chrome on macOS",
            "extension_version": "0.3.0",
        },
    )
    assert response.status_code == 201, response.text
    return response.json(), private_key


def _challenge(client: TestClient, device_id: str):
    return client.post(
        "/v1/extension/session/challenge",
        json={"device_id": device_id, "client_id": CLIENT_ID},
    )


def _challenge_payload(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def test_pair_registers_device_and_retries_are_idempotent_for_the_same_identity() -> None:
    """Dropping device registration or duplicate identity handling breaks pairing retries."""
    with configured_client() as (client, engine):
        workspace, login = _create_workspace_session(client)
        private_key, public_key = _public_key()
        device_id = uuid4()
        for _ in range(2):
            code = client.post(
                f"/v1/workspaces/{workspace['workspace_id']}/extension-pairing-codes",
                headers={"X-CSRF-Token": login["csrf_token"]},
            )
            paired = client.post(
                "/v1/extension/pair",
                headers={"X-Extension-Client": CLIENT_ID},
                json={
                    "pairing_code": code.json()["pairing_code"],
                    "client_id": CLIENT_ID,
                    "device_id": str(device_id),
                    "device_public_key_jwk": public_key,
                    "device_label": "Chrome on macOS",
                    "extension_version": "0.3.0",
                },
            )
            assert paired.status_code == 201, paired.text
            assert paired.json()["device_id"] == str(device_id)
            assert private_key is not None
        with Session(engine) as session:
            assert (
                len(session.scalars(select(ExtensionDeviceBinding)).all()) == 1
            )


def test_challenge_renewal_uses_one_time_signature_and_safe_failures() -> None:
    """Reusing a challenge or revealing a device lookup would weaken session renewal."""
    with configured_client() as (client, _):
        workspace, login = _create_workspace_session(client)
        paired, private_key = _pair_real_device(client, workspace, login)
        challenge = _challenge(client, paired["device_id"])
        assert challenge.status_code == 201, challenge.text
        assert set(challenge.json()) == {
            "challenge_id",
            "device_id",
            "challenge",
            "expires_at",
        }
        signature = sign_raw_p256(
            private_key, _challenge_payload(challenge.json()["challenge"])
        )
        renewed = client.post(
            "/v1/extension/session/renew",
            json={
                "device_id": paired["device_id"],
                "challenge_id": challenge.json()["challenge_id"],
                "signature": signature,
            },
        )
        assert renewed.status_code == 201, renewed.text
        assert renewed.json()["device_id"] == paired["device_id"]
        issued = datetime.fromisoformat(renewed.json()["issued_at"])
        expires = datetime.fromisoformat(renewed.json()["expires_at"])
        assert expires - issued == timedelta(hours=8)

        replay = client.post(
            "/v1/extension/session/renew",
            json={
                "device_id": paired["device_id"],
                "challenge_id": challenge.json()["challenge_id"],
                "signature": signature,
            },
        )
        unknown = _challenge(client, str(uuid4()))
        assert replay.status_code == unknown.status_code == 401
        assert replay.json() == unknown.json() == {"detail": "device session invalid"}

        strict = client.post(
            "/v1/extension/session/renew",
            json={
                "device_id": paired["device_id"],
                "challenge_id": str(uuid4()),
                "signature": signature,
                "unexpected": True,
            },
        )
        assert strict.status_code == 422


def test_admin_lists_redacted_devices_and_revocation_invalidates_device_tokens() -> None:
    """Leaking keys or leaving a revoked device token valid would break device governance."""
    with configured_client() as (client, _):
        workspace, login = _create_workspace_session(client)
        paired, _ = _pair_real_device(client, workspace, login)
        path = f"/v1/workspaces/{workspace['workspace_id']}/extension-devices"
        listed = client.get(path)
        assert listed.status_code == 200, listed.text
        assert len(listed.json()) == 1
        assert set(listed.json()[0]) == {
            "device_id",
            "label",
            "browser",
            "extension_version",
            "created_at",
            "last_used_at",
            "status",
            "revoked_at",
        }
        assert "public_key" not in listed.text
        assert "fingerprint" not in listed.text
        assert "token_hash" not in listed.text

        revoked = client.delete(
            f"{path}/{paired['device_id']}",
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        assert revoked.status_code == 204
        assert client.get(
            "/v1/extension/binding",
            headers={"Authorization": f"Bearer {paired['access_token']}"},
        ).status_code == 401


def test_device_admin_routes_require_admin_session_and_workspace_scope() -> None:
    """Granting device governance to a member, bearer token, or other workspace is unsafe."""
    with configured_client() as (admin, _):
        workspace, login = _create_workspace_session(admin)
        paired, _ = _pair_real_device(admin, workspace, login)
        path = f"/v1/workspaces/{workspace['workspace_id']}/extension-devices"
        invite = admin.post(
            f"/v1/workspaces/{workspace['workspace_id']}/members/codes",
            headers={"X-CSRF-Token": login["csrf_token"]},
            json={"role": "editor"},
        )
        editor = TestClient(app)
        try:
            editor_login = editor.post(
                "/v1/sessions/invite",
                json={"code": invite.json()["code"], "display_name": "设备编辑"},
            ).json()
            assert editor.get(path).status_code == 403
            assert editor.delete(
                f"{path}/{paired['device_id']}",
                headers={"X-CSRF-Token": editor_login["csrf_token"]},
            ).status_code == 403
        finally:
            editor.close()

        viewer_invite = admin.post(
            f"/v1/workspaces/{workspace['workspace_id']}/members/codes",
            headers={"X-CSRF-Token": login["csrf_token"]},
            json={"role": "viewer"},
        )
        viewer = TestClient(app)
        try:
            viewer_login = viewer.post(
                "/v1/sessions/invite",
                json={"code": viewer_invite.json()["code"], "display_name": "设备查看"},
            ).json()
            assert viewer.get(path).status_code == 403
            assert viewer.delete(
                f"{path}/{paired['device_id']}",
                headers={"X-CSRF-Token": viewer_login["csrf_token"]},
            ).status_code == 403
        finally:
            viewer.close()

        other = admin.post("/v1/workspaces", json={"name": "另一工作区"}).json()
        assert admin.get(
            f"/v1/workspaces/{other['workspace_id']}/extension-devices"
        ).status_code == 404
        extension_only = TestClient(app)
        try:
            assert extension_only.get(
                path,
                headers={"Authorization": f"Bearer {paired['access_token']}"},
            ).status_code == 401
            assert extension_only.delete(
                f"{path}/{paired['device_id']}",
                headers={"Authorization": f"Bearer {paired['access_token']}"},
            ).status_code == 401
        finally:
            extension_only.close()


def test_device_bound_token_stops_when_its_member_is_removed() -> None:
    """Skipping active-member checks would keep removed members' devices usable."""
    with configured_client() as (client, engine):
        workspace, login = _create_workspace_session(client)
        paired, _ = _pair_real_device(client, workspace, login)
        with Session(engine) as session:
            member = session.scalar(
                select(WorkspaceMember).where(
                    WorkspaceMember.id == UUID(login["member_id"])
                )
            )
            assert member is not None
            member.revoked_at = datetime.now(UTC)
            session.commit()
        assert client.get(
            "/v1/extension/binding",
            headers={"Authorization": f"Bearer {paired['access_token']}"},
        ).status_code == 401


def test_device_session_routes_are_auth_rate_limited() -> None:
    """Removing auth rate-limit classification would expose renewal to brute force."""
    assert (
        category_for_request("POST", "/v1/extension/session/challenge")
        is RateLimitCategory.AUTH
    )
    assert (
        category_for_request("POST", "/v1/extension/session/renew")
        is RateLimitCategory.AUTH
    )


def test_openapi_device_contracts_never_publish_key_or_token_secrets() -> None:
    """Adding a persisted secret to a public device response must fail contract review."""
    schema = app.openapi()
    device_contract = schema["components"]["schemas"]["ExtensionDeviceRead"]
    pair_contract = schema["components"]["schemas"]["ExtensionPairResponse"]
    public_contract = json.dumps({"device": device_contract, "pair": pair_contract})

    assert {"device_id", "label", "browser", "extension_version"} <= set(
        device_contract["properties"]
    )
    assert "device_id" in pair_contract["properties"]
    assert "public_key_jwk" not in public_contract
    assert "public_key_fingerprint" not in public_contract
    assert "token_hash" not in public_contract
