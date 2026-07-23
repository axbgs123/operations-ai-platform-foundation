from datetime import datetime
from typing import cast
from urllib.parse import urljoin
from uuid import UUID

from celery import shared_task
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionFactory, utc_now
from app.core.security import WorkspaceContext, WorkspaceRole
from app.core.storage import get_storage
from app.modules.risk_rag.ingestion import (
    RiskIngestionService,
    RiskObjectStorage,
)
from app.modules.risk_rag.models import RiskDocument
from app.modules.risk_rag.repository import RiskDocumentRepository
from app.modules.style_facts.fact_tasks import FactFetcher, PinnedHttpTransport
from app.modules.style_facts.url_safety import (
    ValidatedSourceUrl,
    validate_source_url,
)
from app.modules.workspace.models import WorkspaceMember


def _task_context(
    session: Session,
    *,
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
        raise LookupError("active member not found for risk ingestion task")
    return WorkspaceContext(
        workspace_id=workspace_id,
        member_id=member.id,
        role=cast(WorkspaceRole, member.role.value),
    )


def process_web_source(
    session: Session,
    *,
    context: WorkspaceContext,
    document_id: UUID,
    fetcher: FactFetcher,
    storage: RiskObjectStorage,
    accessed_at: datetime,
) -> RiskDocument:
    document = RiskDocumentRepository(session, context=context).get(document_id)
    if (
        document is None
        or document.source_url is None
        or not document.resolved_ips
    ):
        raise LookupError("prepared web risk document not found")
    target = ValidatedSourceUrl(
        url=document.source_url,
        resolved_ips=tuple(document.resolved_ips),
    )
    response = None
    for redirect_count in range(6):
        response = fetcher.request(target)
        target.require_peer(response.peer_ip)
        if response.status in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            if location is None:
                raise ValueError("risk source redirect has no location")
            if redirect_count == 5:
                raise ValueError("risk source exceeded the redirect limit")
            target = validate_source_url(urljoin(target.url, location))
            continue
        if response.status < 200 or response.status >= 300:
            raise ValueError(
                f"risk source request failed with HTTP {response.status}"
            )
        break
    if response is None:  # pragma: no cover
        raise RuntimeError("risk source request did not run")
    content_type = response.headers.get("content-type", "text/plain").split(
        ";", 1
    )[0]
    return RiskIngestionService(
        session,
        context,
        storage=storage,
    ).ingest_web_snapshot(
        document_id,
        content=response.text.encode(),
        mime_type=content_type,
        accessed_at=accessed_at,
        published_at=response.published_at,
        redistribution_authorized=False,
    )


@shared_task(
    name="risk_rag.process_web_source",
    autoretry_for=(ConnectionError, OSError, TimeoutError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def process_risk_web_source_task(
    workspace_id: str,
    member_id: str,
    document_id: str,
) -> None:
    parsed_workspace_id = UUID(workspace_id)
    parsed_member_id = UUID(member_id)
    parsed_document_id = UUID(document_id)
    with SessionFactory() as session:
        context = _task_context(
            session,
            workspace_id=parsed_workspace_id,
            member_id=parsed_member_id,
        )
        process_web_source(
            session,
            context=context,
            document_id=parsed_document_id,
            fetcher=PinnedHttpTransport(),
            storage=get_storage(),
            accessed_at=utc_now(),
        )
        session.commit()
