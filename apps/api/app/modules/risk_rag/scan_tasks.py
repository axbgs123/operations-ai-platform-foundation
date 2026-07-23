from typing import cast
from uuid import UUID

from celery import shared_task
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionFactory
from app.core.security import WorkspaceContext, WorkspaceRole
from app.modules.risk_rag.scanner import (
    RiskScanInput,
    RiskScanService,
    build_default_pipeline,
)
from app.modules.workspace.models import WorkspaceMember


def resolve_scan_task_context(
    session: Session,
    workspace_id: UUID,
    member_id: UUID,
) -> WorkspaceContext:
    member = session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.id == member_id,
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.revoked_at.is_(None),
        )
    )
    if member is None:
        raise LookupError("active member not found for risk scan task")
    return WorkspaceContext(
        workspace_id=workspace_id,
        member_id=member.id,
        role=cast(WorkspaceRole, member.role.value),
    )


@shared_task(
    name="risk_rag.execute_scan",
    autoretry_for=(ConnectionError, OSError, TimeoutError),
    retry_backoff=True,
    max_retries=3,
)
def risk_scan_task(
    workspace_id: str,
    member_id: str,
    payload: dict[str, object],
) -> str:
    parsed_workspace_id = UUID(workspace_id)
    parsed_member_id = UUID(member_id)
    scan_input = RiskScanInput.model_validate(payload)
    with SessionFactory() as session:
        context = resolve_scan_task_context(
            session,
            parsed_workspace_id,
            parsed_member_id,
        )
        scan = RiskScanService(session, context=context).execute(
            scan_input,
            pipeline=build_default_pipeline(session, scan_input),
        )
        session.commit()
        return str(scan.id)
