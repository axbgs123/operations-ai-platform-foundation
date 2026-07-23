from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.security import WorkspaceContext
from app.modules.content.account_models import Platform
from app.modules.risk_rag.lifecycle import (
    InvalidLifecycleTransition,
    SourcePolicyViolation,
)
from app.modules.risk_rag.repository import RiskDocumentRepository
from app.modules.risk_rag.schemas import (
    RiskDocumentCreate,
    RiskDocumentRead,
    RiskDocumentTransition,
)
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.permissions import PermissionDenied


router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/risk-documents",
    tags=["risk-knowledge"],
)
DatabaseSession = Annotated[Session, Depends(get_session)]


def _context(
    session: Session,
    workspace_id: UUID,
    session_token: str | None,
    csrf_token: str | None,
    *,
    mutation: bool,
) -> WorkspaceContext:
    if session_token is None:
        raise HTTPException(status_code=401, detail="invalid session")
    auth = InviteAuthService(session)
    context = auth.authenticate(session_token)
    if context is None:
        raise HTTPException(status_code=401, detail="invalid session")
    if context.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="workspace not found")
    if mutation and (
        csrf_token is None
        or not auth.validate_csrf(session_token, csrf_token)
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return context


@router.post("", response_model=RiskDocumentRead, status_code=201)
def create_risk_document(
    workspace_id: UUID,
    data: RiskDocumentCreate,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> RiskDocumentRead:
    repository = RiskDocumentRepository(
        session,
        context=_context(
            session,
            workspace_id,
            session_token,
            csrf_token,
            mutation=True,
        ),
    )
    try:
        document = repository.add_private(
            platform=data.platform,
            source_level=data.source_level,
            title=data.title,
            private_document_id=data.private_document_id,
            authorization_status=data.authorization_status,
            published_at=data.published_at,
            effective_at=data.effective_at,
            accessed_at=data.accessed_at,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except SourcePolicyViolation as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return RiskDocumentRead.model_validate(document)


@router.get("/current", response_model=list[RiskDocumentRead])
def list_current_risk_documents(
    workspace_id: UUID,
    platform: Platform,
    at: Annotated[datetime, Query()],
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[RiskDocumentRead]:
    repository = RiskDocumentRepository(
        session,
        context=_context(
            session,
            workspace_id,
            session_token,
            None,
            mutation=False,
        ),
    )
    return [
        RiskDocumentRead.model_validate(document)
        for document in repository.list_current(platform=platform, at=at)
    ]


@router.get("/{document_id}", response_model=RiskDocumentRead)
def get_risk_document(
    workspace_id: UUID,
    document_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> RiskDocumentRead:
    repository = RiskDocumentRepository(
        session,
        context=_context(
            session,
            workspace_id,
            session_token,
            None,
            mutation=False,
        ),
    )
    document = repository.get_historical(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="risk document not found")
    return RiskDocumentRead.model_validate(document)


@router.post("/{document_id}/transitions", response_model=RiskDocumentRead)
def transition_risk_document(
    workspace_id: UUID,
    document_id: UUID,
    data: RiskDocumentTransition,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> RiskDocumentRead:
    repository = RiskDocumentRepository(
        session,
        context=_context(
            session,
            workspace_id,
            session_token,
            csrf_token,
            mutation=True,
        ),
    )
    try:
        document = repository.transition(document_id, data.status)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except InvalidLifecycleTransition as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if document is None:
        raise HTTPException(status_code=404, detail="risk document not found")
    session.commit()
    return RiskDocumentRead.model_validate(document)
