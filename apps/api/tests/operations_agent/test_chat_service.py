from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import pytest

from app.core.database import Base
from app.core.security import WorkspaceContext
from app.modules.exports.json_backup import build_lightweight_manifest
from app.modules.exports.deletion import PRIVATE_WORKSPACE_TABLES
from app.modules.operations_agent.models import AgentChatMessage, AgentChatSession
from app.modules.operations_agent.chat_service import AgentChatService
from app.modules.workspace.models import MemberRole, Workspace, WorkspaceMember
from app.modules.workspace.permissions import PermissionDenied


def _environment() -> tuple[Session, Workspace, WorkspaceMember, WorkspaceMember]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    workspace = Workspace(name="智能体聊天测试")
    session.add(workspace)
    session.flush()
    first = WorkspaceMember(
        workspace_id=workspace.id,
        display_name="成员一",
        role=MemberRole.EDITOR,
    )
    second = WorkspaceMember(
        workspace_id=workspace.id,
        display_name="成员二",
        role=MemberRole.EDITOR,
    )
    session.add_all([first, second])
    session.flush()
    return session, workspace, first, second


def _service(
    session: Session,
    workspace: Workspace,
    member: WorkspaceMember,
    role: str = "editor",
) -> AgentChatService:
    return AgentChatService(
        session,
        WorkspaceContext(
            workspace_id=workspace.id,
            member_id=member.id,
            role=role,  # type: ignore[arg-type]
        ),
    )


def test_chat_history_is_private_ordered_and_idempotent() -> None:
    session, workspace, first, second = _environment()
    service = _service(session, workspace, first)
    chat = service.create(idempotency_key="chat-1")
    duplicate = service.create(idempotency_key="chat-1")
    message = service.append_user_message(
        chat.id,
        content="  帮我分析这个账号最近表现  ",
        idempotency_key="message-1",
    )
    repeated = service.append_user_message(
        chat.id,
        content="帮我分析这个账号最近表现",
        idempotency_key="message-1",
    )

    assert duplicate.id == chat.id
    assert repeated.id == message.id
    detail = service.read(chat.id)
    assert detail.title == "帮我分析这个账号最近表现"
    assert [item.sequence_no for item in detail.messages] == [1]
    assert detail.messages[0].content == "帮我分析这个账号最近表现"
    with pytest.raises(LookupError):
        _service(session, workspace, second).read(chat.id)


def test_chat_history_survives_a_fresh_database_session() -> None:
    session, workspace, first, _ = _environment()
    service = _service(session, workspace, first)
    chat = service.create(idempotency_key="chat-restart")
    message = service.append_user_message(
        chat.id,
        content="服务重启后继续读取",
        idempotency_key="message-restart",
    )
    workspace_id = workspace.id
    member_id = first.id
    chat_id = chat.id
    message_id = message.id
    engine = session.get_bind()
    session.commit()
    session.close()

    with Session(engine, expire_on_commit=False) as restarted_session:
        detail = AgentChatService(
            restarted_session,
            WorkspaceContext(
                workspace_id=workspace_id,
                member_id=member_id,
                role="editor",
            ),
        ).read(chat_id)

    assert [item.id for item in detail.messages] == [message_id]
    assert detail.messages[0].content == "服务重启后继续读取"


def test_archived_chat_is_readable_but_cannot_accept_new_messages() -> None:
    session, workspace, first, _ = _environment()
    service = _service(session, workspace, first)
    chat = service.create(idempotency_key="chat-archive")
    service.archive(chat.id)

    assert service.read(chat.id).status == "archived"
    with pytest.raises(ValueError, match="archived"):
        service.append_user_message(
            chat.id,
            content="继续",
            idempotency_key="after-archive",
        )


def test_viewer_can_read_own_history_but_cannot_write() -> None:
    session, workspace, first, _ = _environment()
    editor = _service(session, workspace, first)
    chat = editor.create(idempotency_key="chat-viewer")
    viewer = _service(session, workspace, first, "viewer")

    assert viewer.read(chat.id).id == chat.id
    with pytest.raises(PermissionDenied):
        viewer.create(idempotency_key="viewer-write")


def test_message_limits_and_idempotency_conflicts_are_rejected() -> None:
    session, workspace, first, _ = _environment()
    service = _service(session, workspace, first)
    chat = service.create(idempotency_key="chat-limits")
    service.append_user_message(
        chat.id,
        content="第一条",
        idempotency_key="same-key",
    )
    with pytest.raises(ValueError, match="idempotency"):
        service.append_user_message(
            chat.id,
            content="不同正文",
            idempotency_key="same-key",
        )
    with pytest.raises(ValueError, match="4000"):
        service.append_user_message(
            chat.id,
            content="字" * 4001,
            idempotency_key="too-long",
        )


def test_lightweight_backup_excludes_chat_bodies_and_deletion_covers_tables() -> None:
    session, workspace, first, _ = _environment()
    context = WorkspaceContext(
        workspace_id=workspace.id,
        member_id=first.id,
        role="editor",
    )
    service = AgentChatService(session, context)
    chat = service.create(idempotency_key="chat-backup-boundary")
    service.append_user_message(
        chat.id,
        content="CHAT_PRIVATE_BODY_MUST_NOT_LEAK",
        idempotency_key="chat-private-message",
    )

    manifest = build_lightweight_manifest(session, context)
    serialized = manifest.model_dump_json()

    assert "CHAT_PRIVATE_BODY_MUST_NOT_LEAK" not in serialized
    assert {
        AgentChatSession.__tablename__,
        AgentChatMessage.__tablename__,
    }.issubset(PRIVATE_WORKSPACE_TABLES)
