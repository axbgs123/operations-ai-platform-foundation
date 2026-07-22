from typing import cast
from uuid import UUID

from celery import shared_task
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionFactory
from app.core.security import WorkspaceContext, WorkspaceRole
from app.modules.style_facts.style_service import StyleProfileService
from app.modules.workspace.models import WorkspaceMember


def resolve_style_task_context(
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
        raise LookupError("active member not found for style task")
    return WorkspaceContext(
        workspace_id=workspace_id,
        member_id=member.id,
        role=cast(WorkspaceRole, member.role.value),
    )


@shared_task(name="style_facts.extract_style_profile")
def extract_style_profile_task(
    workspace_id: str,
    account_id: str,
    member_id: str,
    column_campaign_id: str | None = None,
) -> str:
    parsed_workspace_id = UUID(workspace_id)
    parsed_member_id = UUID(member_id)
    with SessionFactory() as session:
        context = resolve_style_task_context(
            session,
            parsed_workspace_id,
            parsed_member_id,
        )
        profile = StyleProfileService(session, context).extract_profile(
            UUID(account_id),
            UUID(column_campaign_id) if column_campaign_id else None,
        )
        session.commit()
        return str(profile.id)
