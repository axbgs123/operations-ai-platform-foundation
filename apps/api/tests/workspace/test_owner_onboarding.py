from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_session
from app.main import app
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.models import (
    AuditLog,
    MemberRole,
    Workspace,
    WorkspaceAccessCode,
    WorkspaceMember,
    WorkspaceSession,
)
from app.modules.workspace.router import invite_attempts


@contextmanager
def configured_owner_client() -> Iterator[tuple[TestClient, Engine]]:
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
            yield client, engine
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _count(session: Session, model: type[object]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_owner_onboarding_creates_admin_session_without_invite() -> None:
    with configured_owner_client() as (client, engine):
        response = client.post(
            "/v1/workspaces/onboard",
            json={"workspace_name": "C哥内容团队", "display_name": "小白"},
        )

        assert response.status_code == 201, response.text
        assert set(response.json()) == {
            "workspace_id",
            "member_id",
            "csrf_token",
        }
        assert response.cookies.get("session")
        with Session(engine) as session:
            workspace = session.scalar(select(Workspace))
            member = session.scalar(select(WorkspaceMember))
            stored_session = session.scalar(select(WorkspaceSession))
            assert workspace is not None
            assert member is not None
            assert stored_session is not None
            assert _count(session, Workspace) == 1
            assert _count(session, WorkspaceMember) == 1
            assert member.workspace_id == workspace.id
            assert member.role is MemberRole.ADMIN
            assert member.revoked_at is None
            assert _count(session, WorkspaceSession) == 1
            assert stored_session.workspace_id == workspace.id
            assert stored_session.member_id == member.id
            assert stored_session.revoked_at is None
            assert _count(session, WorkspaceAccessCode) == 0
            assert set(session.scalars(select(AuditLog.action))) == {
                "workspace.created",
                "member.owner_created",
                "session.created",
            }


def test_owner_onboarding_response_never_contains_credentials() -> None:
    with configured_owner_client() as (client, engine):
        response = client.post(
            "/v1/workspaces/onboard",
            json={"workspace_name": "安全团队", "display_name": "管理员"},
        )

        assert response.status_code == 201, response.text
        payload = response.json()
        assert "admin_code" not in payload
        assert "session_token" not in payload
        assert "invite" not in payload
        assert set(payload) == {"workspace_id", "member_id", "csrf_token"}
        with Session(engine) as session:
            assert _count(session, WorkspaceAccessCode) == 0
            audit_payload = " ".join(
                str(record.details) for record in session.scalars(select(AuditLog))
            )
        assert response.cookies["session"] not in response.text
        assert response.cookies["session"] not in audit_payload
        assert payload["csrf_token"] not in audit_payload


def test_owner_onboarding_trims_names_before_storage() -> None:
    with configured_owner_client() as (client, engine):
        response = client.post(
            "/v1/workspaces/onboard",
            json={
                "workspace_name": "  C哥内容团队  ",
                "display_name": "  小白  ",
            },
        )

        assert response.status_code == 201, response.text
        with Session(engine) as session:
            assert session.scalar(select(Workspace.name)) == "C哥内容团队"
            assert session.scalar(select(WorkspaceMember.display_name)) == "小白"


@pytest.mark.parametrize("field", ("workspace_name", "display_name"))
def test_owner_onboarding_rejects_blank_names_without_writes(field: str) -> None:
    payload = {"workspace_name": "团队", "display_name": "管理员"}
    payload[field] = " \t "
    with configured_owner_client() as (client, engine):
        response = client.post("/v1/workspaces/onboard", json=payload)

        assert response.status_code == 422
        with Session(engine) as session:
            assert _count(session, Workspace) == 0
            assert _count(session, WorkspaceMember) == 0
            assert _count(session, WorkspaceSession) == 0
            assert _count(session, AuditLog) == 0
            assert _count(session, WorkspaceAccessCode) == 0


def test_owner_onboarding_rolls_back_every_record_when_session_creation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_session_creation(
        _service: InviteAuthService,
        _member: WorkspaceMember,
    ) -> None:
        raise RuntimeError("synthetic session failure")

    monkeypatch.setattr(
        InviteAuthService,
        "_create_session",
        fail_session_creation,
        raising=False,
    )
    with configured_owner_client() as (client, engine):
        with pytest.raises(RuntimeError, match="synthetic session failure"):
            client.post(
                "/v1/workspaces/onboard",
                json={"workspace_name": "回滚团队", "display_name": "管理员"},
            )

        with Session(engine) as session:
            assert _count(session, Workspace) == 0
            assert _count(session, WorkspaceMember) == 0
            assert _count(session, WorkspaceSession) == 0
            assert _count(session, AuditLog) == 0
            assert _count(session, WorkspaceAccessCode) == 0


def test_owner_sessions_are_isolated_between_workspaces() -> None:
    with configured_owner_client() as (first_client, _):
        with TestClient(app) as second_client:
            first = first_client.post(
                "/v1/workspaces/onboard",
                json={"workspace_name": "团队甲", "display_name": "甲管理员"},
            )
            second = second_client.post(
                "/v1/workspaces/onboard",
                json={"workspace_name": "团队乙", "display_name": "乙管理员"},
            )
            assert first.status_code == second.status_code == 201

            first_workspace = first.json()["workspace_id"]
            second_workspace = second.json()["workspace_id"]
            first_context = first_client.get(
                f"/v1/workspaces/{first_workspace}/workbench/context"
            )
            second_context = second_client.get(
                f"/v1/workspaces/{second_workspace}/workbench/context"
            )
            cross_workspace = first_client.get(
                f"/v1/workspaces/{second_workspace}/workbench/context"
            )

            assert first_context.status_code == 200, first_context.text
            assert second_context.status_code == 200, second_context.text
            assert first_context.json()["role"] == "admin"
            assert second_context.json()["role"] == "admin"
            assert first_context.json()["workspace_id"] == first_workspace
            assert second_context.json()["workspace_id"] == second_workspace
            assert cross_workspace.status_code == 404
