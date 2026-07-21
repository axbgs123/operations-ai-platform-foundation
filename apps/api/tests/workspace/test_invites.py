from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.modules.workspace.auth import (
    InviteAuthService,
    InviteRateLimitExceeded,
    InvalidInviteCode,
)
from app.modules.workspace.models import (
    AuditLog,
    WorkspaceAccessCode,
    WorkspaceMember,
    WorkspaceSession,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as database_session:
        yield database_session


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 7, 21, 4, 0, tzinfo=UTC)


def test_workspace_creation_returns_plain_code_once_but_stores_only_argon2id_hash(
    session: Session,
    now: datetime,
) -> None:
    service = InviteAuthService(session, now=lambda: now)

    issued = service.create_workspace("秋招运营项目")
    session.commit()

    stored_code = session.scalar(select(WorkspaceAccessCode))
    assert stored_code is not None
    assert issued.admin_code.startswith(f"{stored_code.id}.")
    assert stored_code.code_hash.startswith("$argon2id$")
    assert issued.admin_code not in stored_code.code_hash
    assert not {"code", "plain_code"} & set(WorkspaceAccessCode.__table__.columns.keys())


def test_first_redemption_binds_member_and_reuse_creates_only_a_new_session(
    session: Session,
    now: datetime,
) -> None:
    service = InviteAuthService(session, now=lambda: now)
    issued = service.create_workspace("复用测试")

    first = service.redeem(
        issued.admin_code,
        display_name="小白",
        client_key="127.0.0.1",
    )
    second = service.redeem(
        issued.admin_code,
        display_name="不会覆盖原名",
        client_key="127.0.0.1",
    )
    session.commit()

    members = list(session.scalars(select(WorkspaceMember)))
    sessions = list(session.scalars(select(WorkspaceSession)))
    assert len(members) == 1
    assert members[0].display_name == "小白"
    assert first.member_id == second.member_id == members[0].id
    assert len(sessions) == 2
    assert first.session_token != second.session_token
    assert all(record.token_hash not in {first.session_token, second.session_token} for record in sessions)


def test_revoking_member_invalidates_existing_session(
    session: Session,
    now: datetime,
) -> None:
    service = InviteAuthService(session, now=lambda: now)
    issued = service.create_workspace("撤销测试")
    authenticated = service.redeem(
        issued.admin_code,
        display_name="管理员",
        client_key="127.0.0.1",
    )

    assert service.authenticate(authenticated.session_token) is not None
    service.revoke_member(authenticated.context, authenticated.member_id)
    session.commit()
    assert service.authenticate(authenticated.session_token) is None
    access_code = session.scalar(select(WorkspaceAccessCode))
    assert access_code is not None and access_code.revoked_at == now
    assert "invite.revoked" in set(session.scalars(select(AuditLog.action)))


def test_invite_attempts_are_rate_limited_even_when_codes_are_invalid(
    session: Session,
    now: datetime,
) -> None:
    service = InviteAuthService(
        session,
        now=lambda: now,
        max_attempts=3,
        attempt_window=timedelta(minutes=1),
    )

    for attempt in range(3):
        with pytest.raises(InvalidInviteCode):
            service.redeem(
                f"bad-code-{attempt}",
                display_name="测试",
                client_key="same-client",
            )

    with pytest.raises(InviteRateLimitExceeded):
        service.redeem(
            "bad-code-final",
            display_name="测试",
            client_key="same-client",
        )


def test_audit_log_never_contains_plain_invite_or_session_tokens(
    session: Session,
    now: datetime,
) -> None:
    service = InviteAuthService(session, now=lambda: now)
    issued = service.create_workspace("审计测试")
    authenticated = service.redeem(
        issued.admin_code,
        display_name="管理员",
        client_key="127.0.0.1",
    )
    session.commit()

    audit_payload = " ".join(
        str(log.details) for log in session.scalars(select(AuditLog))
    )
    assert issued.admin_code not in audit_payload
    assert authenticated.session_token not in audit_payload
    assert authenticated.csrf_token not in audit_payload
