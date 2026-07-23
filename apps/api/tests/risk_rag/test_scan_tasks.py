from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.modules.risk_rag.scan_tasks import (
    resolve_scan_task_context,
    risk_scan_task,
)
from app.modules.workspace.models import Workspace, WorkspaceMember


def test_risk_scan_task_has_bounded_retries_and_workspace_identity() -> None:
    assert risk_scan_task.name == "risk_rag.execute_scan"
    assert risk_scan_task.max_retries == 3
    assert risk_scan_task.retry_backoff is True
    assert risk_scan_task.autoretry_for == (
        ConnectionError,
        OSError,
        TimeoutError,
    )


def test_task_context_requires_active_member_in_exact_workspace() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        workspace = Workspace(name="task-workspace")
        other = Workspace(name="other-task-workspace")
        member = WorkspaceMember(
            workspace_id=workspace.id,
            display_name="task-editor",
            role="editor",
        )
        session.add_all([workspace, other, member])
        session.commit()

        context = resolve_scan_task_context(
            session,
            workspace.id,
            member.id,
        )
        assert context.workspace_id == workspace.id
        assert context.role == "editor"
        with pytest.raises(LookupError):
            resolve_scan_task_context(session, other.id, member.id)
        with pytest.raises(LookupError):
            resolve_scan_task_context(session, workspace.id, uuid4())
