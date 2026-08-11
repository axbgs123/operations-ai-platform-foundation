import base64
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.imports import extension_router as extension_router_module
from app.core.rate_limit import RateLimitCategory, category_for_request
from app.main import app
from app.modules.imports.models import ExtensionDeviceBinding, ExtensionToken
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
        code = client.post(
            f"/v1/workspaces/{workspace['workspace_id']}/extension-pairing-codes",
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        payload = {
            "pairing_code": code.json()["pairing_code"],
            "client_id": CLIENT_ID,
            "device_id": str(device_id),
            "device_public_key_jwk": public_key,
            "device_label": "Chrome on macOS",
            "extension_version": "0.3.0",
        }
        for _ in range(2):
            paired = client.post(
                "/v1/extension/pair",
                headers={"X-Extension-Client": CLIENT_ID},
                json=payload,
            )
            assert paired.status_code == 201, paired.text
            assert paired.json()["device_id"] == str(device_id)
            assert private_key is not None
        changed_payload = {**payload, "device_label": "Different browser"}
        assert client.post(
            "/v1/extension/pair",
            headers={"X-Extension-Client": CLIENT_ID},
            json=changed_payload,
        ).json() == {"detail": "pairing code invalid or expired"}
        with Session(engine) as session:
            assert (
                len(session.scalars(select(ExtensionDeviceBinding)).all()) == 1
            )


def test_pairing_infrastructure_failure_matches_the_documented_retryable_status() -> None:
    """The pair route must not advertise 503 while returning 500 for the same outage."""

    class UnavailablePairingService:
        def __init__(self, _session):
            pass

        def redeem(self, *_args, **_kwargs):
            raise RuntimeError("isolated pairing storage outage")

    with configured_client() as (client, _):
        workspace, login = _create_workspace_session(client)
        code = client.post(
            f"/v1/workspaces/{workspace['workspace_id']}/extension-pairing-codes",
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        _, public_key = _public_key()
        original = extension_router_module.ExtensionPairingService
        try:
            extension_router_module.ExtensionPairingService = UnavailablePairingService
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
        finally:
            extension_router_module.ExtensionPairingService = original

    assert response.status_code == 503
    assert response.json() == {"detail": "pairing unavailable"}


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
        unknown_device_id = str(uuid4())
        unknown = _challenge(client, unknown_device_id)
        assert unknown.status_code == 201
        assert set(unknown.json()) == set(challenge.json())
        assert unknown.json()["device_id"] == unknown_device_id
        unknown_renewal = client.post(
            "/v1/extension/session/renew",
            json={
                "device_id": unknown_device_id,
                "challenge_id": unknown.json()["challenge_id"],
                "signature": "A" * 86,
            },
        )
        assert replay.status_code == unknown_renewal.status_code == 401
        assert replay.json() == unknown_renewal.json() == {
            "detail": "device session invalid"
        }

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


def test_revoked_and_unknown_devices_receive_indistinguishable_challenges() -> None:
    """Returning an early 401 would expose whether a public device ID is active."""
    with configured_client() as (client, _):
        workspace, login = _create_workspace_session(client)
        paired, _ = _pair_real_device(client, workspace, login)
        path = f"/v1/workspaces/{workspace['workspace_id']}/extension-devices"
        assert client.delete(
            f"{path}/{paired['device_id']}",
            headers={"X-CSRF-Token": login["csrf_token"]},
        ).status_code == 204

        revoked = _challenge(client, paired["device_id"])
        unknown_id = str(uuid4())
        unknown = _challenge(client, unknown_id)

        assert revoked.status_code == unknown.status_code == 201
        assert set(revoked.json()) == set(unknown.json()) == {
            "challenge_id",
            "device_id",
            "challenge",
            "expires_at",
        }
        assert revoked.json()["device_id"] == paired["device_id"]
        assert unknown.json()["device_id"] == unknown_id


def test_renewal_infrastructure_failure_is_retryable_not_terminal() -> None:
    """Converting Redis or database outages to 401 destroys a valid local identity."""

    class UnavailableDevices:
        def renew_public_session(self, **_kwargs):
            raise RuntimeError("isolated Redis outage")

    with configured_client() as (client, _):
        namespaced_factory = extension_router_module._extension_devices
        try:
            extension_router_module._extension_devices = (
                lambda _session: UnavailableDevices()
            )
            response = client.post(
                "/v1/extension/session/renew",
                json={
                    "device_id": str(uuid4()),
                    "challenge_id": str(uuid4()),
                    "signature": "A" * 86,
                },
            )
        finally:
            extension_router_module._extension_devices = namespaced_factory
    assert response.status_code == 503
    assert response.json() == {"detail": "device session unavailable"}


def test_self_unlink_revokes_the_device_and_every_issued_token_transactionally() -> None:
    """Revoking only the caller token leaves an unrecoverable active device orphan."""
    with configured_client() as (client, engine):
        workspace, login = _create_workspace_session(client)
        paired, private_key = _pair_real_device(client, workspace, login)
        challenge = _challenge(client, paired["device_id"])
        renewed = client.post(
            "/v1/extension/session/renew",
            json={
                "device_id": paired["device_id"],
                "challenge_id": challenge.json()["challenge_id"],
                "signature": sign_raw_p256(
                    private_key,
                    _challenge_payload(challenge.json()["challenge"]),
                ),
            },
        ).json()

        response = client.delete(
            "/v1/extension/binding",
            headers={"Authorization": f"Bearer {paired['access_token']}"},
        )
        assert response.status_code == 204

        with Session(engine) as session:
            device = session.scalar(select(ExtensionDeviceBinding))
            assert device is not None and device.revoked_at is not None
            tokens = session.scalars(
                select(ExtensionToken).where(ExtensionToken.device_id == device.id)
            ).all()
            assert len(tokens) == 2
            assert all(token.revoked_at is not None for token in tokens)
        for token in (paired["access_token"], renewed["access_token"]):
            assert client.get(
                "/v1/extension/binding",
                headers={"Authorization": f"Bearer {token}"},
            ).status_code == 401


def test_admin_lists_redacted_devices_and_revocation_invalidates_device_tokens() -> None:
    """Leaking keys or leaving a revoked device token valid would break device governance."""
    with configured_client() as (client, _):
        workspace, login = _create_workspace_session(client)
        paired, _ = _pair_real_device(client, workspace, login)
        path = f"/v1/workspaces/{workspace['workspace_id']}/extension-devices"
        listed = client.get(path, headers={"X-CSRF-Token": login["csrf_token"]})
        assert listed.status_code == 200, listed.text
        assert len(listed.json()) == 1
        assert set(listed.json()[0]) == {
            "device_id",
            "label",
            "device_description",
            "extension_version",
            "created_at",
            "last_session_issued_at",
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


def test_public_device_routes_reject_internal_binding_identifiers() -> None:
    """Accepting a binding primary key at a public route would expose an internal ID."""
    with configured_client() as (client, engine):
        workspace, login = _create_workspace_session(client)
        paired, private_key = _pair_real_device(client, workspace, login)
        with Session(engine) as session:
            binding = session.scalar(select(ExtensionDeviceBinding))
            assert binding is not None
            internal_id = str(binding.id)

        internal_challenge = _challenge(client, internal_id)
        assert internal_challenge.status_code == 201
        assert internal_challenge.json()["device_id"] == internal_id
        challenge = _challenge(client, paired["device_id"])
        signature = sign_raw_p256(
            private_key, _challenge_payload(challenge.json()["challenge"])
        )
        assert client.post(
            "/v1/extension/session/renew",
            json={
                "device_id": internal_id,
                "challenge_id": challenge.json()["challenge_id"],
                "signature": signature,
            },
        ).json() == {"detail": "device session invalid"}
        assert client.delete(
            f"/v1/workspaces/{workspace['workspace_id']}/extension-devices/{internal_id}",
            headers={"X-CSRF-Token": login["csrf_token"]},
        ).status_code == 404


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
            assert editor.get(
                path, headers={"X-CSRF-Token": editor_login["csrf_token"]}
            ).status_code == 403
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
            assert viewer.get(
                path, headers={"X-CSRF-Token": viewer_login["csrf_token"]}
            ).status_code == 403
            assert viewer.delete(
                f"{path}/{paired['device_id']}",
                headers={"X-CSRF-Token": viewer_login["csrf_token"]},
            ).status_code == 403
        finally:
            viewer.close()

        other = admin.post("/v1/workspaces", json={"name": "另一工作区"}).json()
        assert admin.get(
            f"/v1/workspaces/{other['workspace_id']}/extension-devices",
            headers={"X-CSRF-Token": login["csrf_token"]},
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


def test_device_list_requires_csrf_after_workspace_scope_check() -> None:
    """Reading governed devices without CSRF would permit a cross-site credentialed read."""
    with configured_client() as (client, _):
        workspace, login = _create_workspace_session(client)
        _pair_real_device(client, workspace, login)
        path = f"/v1/workspaces/{workspace['workspace_id']}/extension-devices"
        assert client.get(path).status_code == 403
        assert client.get(path, headers={"X-CSRF-Token": "invalid"}).status_code == 403
        other = client.post("/v1/workspaces", json={"name": "越权读取工作区"}).json()
        assert client.get(
            f"/v1/workspaces/{other['workspace_id']}/extension-devices"
        ).status_code == 404


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

    assert {
        "device_id",
        "label",
        "device_description",
        "extension_version",
        "last_session_issued_at",
    } <= set(
        device_contract["properties"]
    )
    assert "device_id" in pair_contract["properties"]
    assert "public_key_jwk" not in public_contract
    assert "public_key_fingerprint" not in public_contract
    assert "token_hash" not in public_contract
    jwk_contract = schema["components"]["schemas"]["ExtensionDevicePublicJwk"]
    assert jwk_contract["additionalProperties"] is False
    assert jwk_contract["properties"]["kty"]["const"] == "EC"
    assert jwk_contract["properties"]["crv"]["const"] == "P-256"
    list_operation = schema["paths"][
        "/v1/workspaces/{workspace_id}/extension-devices"
    ]["get"]
    assert next(
        parameter
        for parameter in list_operation["parameters"]
        if parameter["in"] == "header" and parameter["name"] == "X-CSRF-Token"
    )["required"] is True
    assert schema["paths"]["/v1/extension/pair"]["post"]["responses"]["422"][
        "content"
    ]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ExtensionSafeError"
    }
    for path, method, statuses in (
        ("/v1/extension/pair", "post", ("401", "422")),
        ("/v1/extension/session/challenge", "post", ("401", "422", "503")),
        ("/v1/extension/session/renew", "post", ("401", "422", "503")),
        (
            "/v1/workspaces/{workspace_id}/extension-devices",
            "get",
            ("401", "403", "404"),
        ),
    ):
        responses = schema["paths"][path][method]["responses"]
        for status in statuses:
            assert responses[status]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ExtensionSafeError"
            }
