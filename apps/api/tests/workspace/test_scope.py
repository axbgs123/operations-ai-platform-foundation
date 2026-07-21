from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.security import WorkspaceContext
from app.modules.workspace.models import (
    AuditLog,
    Workspace,
    WorkspaceAccessCode,
    WorkspaceMember,
)
from app.modules.workspace.repository import WorkspaceMemberRepository


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        yield database_session


def test_repository_cannot_be_created_without_workspace_context(
    session: Session,
) -> None:
    with pytest.raises(TypeError):
        WorkspaceMemberRepository(session)  # type: ignore[call-arg]

    with pytest.raises(ValueError, match="workspace context"):
        WorkspaceMemberRepository(session, context=None)  # type: ignore[arg-type]


def test_resource_id_from_another_workspace_is_not_visible(session: Session) -> None:
    workspace_a = Workspace(name="工作区 A")
    workspace_b = Workspace(name="工作区 B")
    member_a = WorkspaceMember(
        workspace_id=workspace_a.id,
        display_name="成员 A",
        role="editor",
    )
    session.add_all([workspace_a, workspace_b, member_a])
    session.commit()

    allowed = WorkspaceMemberRepository(
        session,
        context=WorkspaceContext(
            workspace_id=workspace_a.id,
            member_id=member_a.id,
            role="editor",
        ),
    )
    wrong_workspace = WorkspaceMemberRepository(
        session,
        context=WorkspaceContext(
            workspace_id=workspace_b.id,
            member_id=uuid4(),
            role="admin",
        ),
    )

    assert allowed.get(member_a.id) is member_a
    assert wrong_workspace.get(member_a.id) is None


def test_list_never_returns_members_from_another_workspace(session: Session) -> None:
    workspace_a = Workspace(name="工作区 A")
    workspace_b = Workspace(name="工作区 B")
    member_a = WorkspaceMember(
        workspace_id=workspace_a.id,
        display_name="成员 A",
        role="editor",
    )
    member_b = WorkspaceMember(
        workspace_id=workspace_b.id,
        display_name="成员 B",
        role="viewer",
    )
    session.add_all([workspace_a, workspace_b, member_a, member_b])
    session.commit()

    repository = WorkspaceMemberRepository(
        session,
        context=WorkspaceContext(
            workspace_id=workspace_a.id,
            member_id=member_a.id,
            role="editor",
        ),
    )

    assert repository.list() == [member_a]


def test_foundation_ids_are_uuid7_and_timestamps_are_timezone_aware() -> None:
    workspace = Workspace(name="版本测试")
    member = WorkspaceMember(
        workspace_id=workspace.id,
        display_name="版本成员",
        role="viewer",
    )
    access_code = WorkspaceAccessCode(
        workspace_id=workspace.id,
        code_hash="argon2id hash placeholder",
        role="viewer",
    )
    audit_log = AuditLog(
        workspace_id=workspace.id,
        action="workspace.created",
        resource_type="workspace",
    )

    for record in (workspace, member, access_code, audit_log):
        assert record.id.version == 7
        assert record.created_at.tzinfo is not None

    for record in (workspace, member, access_code):
        assert record.updated_at.tzinfo is not None
