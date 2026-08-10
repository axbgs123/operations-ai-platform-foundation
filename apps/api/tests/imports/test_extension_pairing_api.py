from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.rate_limit import (
    RateLimitBackendUnavailable,
    RateLimitCategory,
    RateLimiter,
    category_for_request,
)
from app.main import app
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.models import MemberRole, WorkspaceMember
from tests.imports.helpers import configured_client


CLIENT_ID = "operations-capture-extension"
PAIR_PATH = "/v1/extension/pair"


def _create_workspace_session(client: TestClient) -> tuple[dict, dict]:
    workspace = client.post("/v1/workspaces", json={"name": "合成配对工作区"}).json()
    login = client.post(
        "/v1/sessions/invite",
        json={"code": workspace["admin_code"], "display_name": "配对管理员"},
    )
    assert login.status_code == 201, login.text
    return workspace, login.json()


def _create_member_client(
    admin: TestClient,
    *,
    workspace_id: str,
    csrf: str,
    role: str,
) -> tuple[TestClient, dict]:
    invitation = admin.post(
        f"/v1/workspaces/{workspace_id}/members/codes",
        headers={"X-CSRF-Token": csrf},
        json={"role": role},
    )
    assert invitation.status_code == 201, invitation.text
    member = TestClient(app)
    login = member.post(
        "/v1/sessions/invite",
        json={
            "code": invitation.json()["code"],
            "display_name": f"配对{role}",
        },
    )
    assert login.status_code == 201, login.text
    return member, login.json()


def _create_code(client: TestClient, *, workspace_id: str, csrf: str):
    return client.post(
        f"/v1/workspaces/{workspace_id}/extension-pairing-codes",
        headers={"X-CSRF-Token": csrf},
    )


def _pair(client: TestClient, pairing_code: str, *, client_id: str = CLIENT_ID):
    return client.post(
        PAIR_PATH,
        headers={"X-Extension-Client": client_id},
        json={"pairing_code": pairing_code, "client_id": client_id},
    )


def test_admin_pairing_code_redeems_once_without_creating_a_member() -> None:
    """Removing code creation/redemption or issuing a member would break this."""
    with configured_client() as (client, engine):
        workspace, login = _create_workspace_session(client)
        with Session(engine) as session:
            before_members = session.scalar(
                select(func.count())
                .select_from(WorkspaceMember)
                .where(WorkspaceMember.workspace_id == UUID(workspace["workspace_id"]))
            )

        created = _create_code(
            client,
            workspace_id=workspace["workspace_id"],
            csrf=login["csrf_token"],
        )

        assert created.status_code == 201, created.text
        assert set(created.json()) == {
            "pairing_code",
            "expires_at",
            "workspace_id",
            "workspace_name",
        }
        assert created.json()["workspace_id"] == workspace["workspace_id"]
        assert created.json()["workspace_name"] == "合成配对工作区"
        assert len(created.json()["pairing_code"]) == 8
        assert "member_id" not in created.text
        assert "access_token" not in created.text

        paired = _pair(client, created.json()["pairing_code"])

        assert paired.status_code == 201, paired.text
        assert paired.json()["workspace_name"] == "合成配对工作区"
        assert paired.json()["member_display_name"] == "配对管理员"
        assert paired.json()["web_origin"] == "http://localhost:3000"
        assert paired.json()["member_id"] == login["member_id"]
        assert paired.json()["client_id"] == CLIENT_ID
        assert paired.json()["scopes"] == [
            "capture:create",
            "capture:upload",
            "capture:read",
        ]

        with Session(engine) as session:
            after_members = session.scalar(
                select(func.count())
                .select_from(WorkspaceMember)
                .where(WorkspaceMember.workspace_id == UUID(workspace["workspace_id"]))
            )
        assert after_members == before_members

        replay = _pair(client, created.json()["pairing_code"])
        assert replay.status_code == 401
        assert replay.json() == {"detail": "pairing code invalid or expired"}
        assert created.json()["pairing_code"] not in replay.text

        binding = client.get(
            "/v1/extension/binding",
            headers={"Authorization": f"Bearer {paired.json()['access_token']}"},
        )
        assert binding.status_code == 200, binding.text
        assert binding.json()["workspace_name"] == "合成配对工作区"
        assert binding.json()["member_display_name"] == "配对管理员"
        assert binding.json()["web_origin"] == "http://localhost:3000"
        assert "pairing_code" not in binding.text
        assert "access_token" not in binding.text


def test_editor_can_create_code_but_read_only_and_extension_auth_cannot() -> None:
    """Weakening WRITE_CONTENT or accepting bearer auth on this web route breaks this."""
    with configured_client() as (admin, engine):
        workspace, admin_login = _create_workspace_session(admin)
        editor, editor_login = _create_member_client(
            admin,
            workspace_id=workspace["workspace_id"],
            csrf=admin_login["csrf_token"],
            role="editor",
        )
        try:
            created = _create_code(
                editor,
                workspace_id=workspace["workspace_id"],
                csrf=editor_login["csrf_token"],
            )
            assert created.status_code == 201, created.text
            paired = _pair(editor, created.json()["pairing_code"])
            assert paired.status_code == 201, paired.text
            assert paired.json()["member_id"] == editor_login["member_id"]

            for role in ("viewer",):
                member, member_login = _create_member_client(
                    admin,
                    workspace_id=workspace["workspace_id"],
                    csrf=admin_login["csrf_token"],
                    role=role,
                )
                try:
                    denied = _create_code(
                        member,
                        workspace_id=workspace["workspace_id"],
                        csrf=member_login["csrf_token"],
                    )
                    assert denied.status_code == 403
                    assert denied.json() == {"detail": "permission denied"}
                finally:
                    member.close()

            with Session(engine) as session:
                admin_session = admin.cookies.get("session")
                assert admin_session is not None
                context = InviteAuthService(session).authenticate(admin_session)
                assert context is not None
                demo_code = InviteAuthService(session).issue_member_code(
                    context,
                    MemberRole.DEMO,
                )
                session.commit()
            demo = TestClient(app)
            try:
                demo_login = demo.post(
                    "/v1/sessions/invite",
                    json={"code": demo_code, "display_name": "配对demo"},
                )
                assert demo_login.status_code == 201, demo_login.text
                denied = _create_code(
                    demo,
                    workspace_id=workspace["workspace_id"],
                    csrf=demo_login.json()["csrf_token"],
                )
                assert denied.status_code == 403
                assert denied.json() == {"detail": "permission denied"}
            finally:
                demo.close()

            extension_only = TestClient(app)
            try:
                rejected = extension_only.post(
                    f"/v1/workspaces/{workspace['workspace_id']}/extension-pairing-codes",
                    headers={
                        "Authorization": f"Bearer {paired.json()['access_token']}",
                        "X-CSRF-Token": editor_login["csrf_token"],
                    },
                )
                assert rejected.status_code == 401
                assert rejected.json() == {"detail": "invalid session"}
            finally:
                extension_only.close()
        finally:
            editor.close()


def test_pairing_creation_requires_csrf_and_workspace_scope() -> None:
    """Removing session CSRF or workspace checks would make these requests succeed."""
    with configured_client() as (client, _):
        workspace, login = _create_workspace_session(client)
        missing_csrf = client.post(
            f"/v1/workspaces/{workspace['workspace_id']}/extension-pairing-codes"
        )
        assert missing_csrf.status_code == 403
        assert missing_csrf.json() == {"detail": "CSRF validation failed"}

        other = client.post("/v1/workspaces", json={"name": "其他配对工作区"}).json()
        cross_workspace = _create_code(
            client,
            workspace_id=other["workspace_id"],
            csrf=login["csrf_token"],
        )
        assert cross_workspace.status_code == 404
        assert cross_workspace.json() == {"detail": "workspace not found"}


def test_old_invalid_and_mismatched_client_exchange_errors_do_not_reveal_codes() -> (
    None
):
    """Accepting revoked codes or exposing their state would break this exchange contract."""
    with configured_client() as (client, _):
        workspace, login = _create_workspace_session(client)
        first = _create_code(
            client,
            workspace_id=workspace["workspace_id"],
            csrf=login["csrf_token"],
        )
        second = _create_code(
            client,
            workspace_id=workspace["workspace_id"],
            csrf=login["csrf_token"],
        )
        assert first.status_code == second.status_code == 201

        stale = _pair(client, first.json()["pairing_code"])
        invalid = _pair(client, "ABCD-1234")
        mismatched = client.post(
            PAIR_PATH,
            headers={"X-Extension-Client": CLIENT_ID},
            json={
                "pairing_code": second.json()["pairing_code"],
                "client_id": "other-client",
            },
        )
        missing_header = client.post(
            PAIR_PATH,
            json={
                "pairing_code": second.json()["pairing_code"],
                "client_id": CLIENT_ID,
            },
        )

        assert stale.status_code == invalid.status_code == 401
        assert (
            stale.json()
            == invalid.json()
            == {"detail": "pairing code invalid or expired"}
        )
        assert first.json()["pairing_code"] not in stale.text
        assert "ABCD-1234" not in invalid.text
        assert mismatched.status_code == 422
        assert missing_header.status_code == 422
        assert second.json()["pairing_code"] not in mismatched.text
        assert second.json()["pairing_code"] not in missing_header.text


class _UnavailableLimiterBackend:
    def increment(self, *args, **kwargs):
        raise RuntimeError("limiter offline")


def test_pair_exchange_uses_fail_closed_auth_rate_limits() -> None:
    """Changing pair classification or allowing limiter outages would break this."""
    assert category_for_request("POST", PAIR_PATH) is RateLimitCategory.AUTH
    with pytest.raises(RateLimitBackendUnavailable):
        RateLimiter(_UnavailableLimiterBackend()).check(
            RateLimitCategory.AUTH,
            "pairing-test-client",
        )


def test_pair_exchange_rate_limits_invalid_codes() -> None:
    """Removing pairing attempt accounting would stop the eleventh bad exchange."""
    with configured_client() as (client, _):
        for _ in range(10):
            invalid = _pair(client, "ABCD-1234")
            assert invalid.status_code == 401
            assert invalid.json() == {"detail": "pairing code invalid or expired"}

        limited = _pair(client, "ABCD-1234")

        assert limited.status_code == 429
        assert limited.json() == {"detail": "too many attempts"}
        assert "ABCD-1234" not in limited.text
