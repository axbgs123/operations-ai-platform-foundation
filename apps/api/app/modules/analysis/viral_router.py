from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.modules.analysis.viral import (
    ViralCandidateRead,
    ViralConfirmationInput,
    ViralEvaluationInput,
    ViralLibraryItemRead,
    ViralRevocationInput,
    ViralService,
    ViralThresholdInput,
    ViralThresholdRead,
)
from app.modules.analysis.viral_models import ViralThresholdProfile
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.permissions import PermissionDenied


router = APIRouter(tags=["viral-library"])
DatabaseSession = Annotated[Session, Depends(get_session)]


def _service(
    session: Session,
    session_token: str | None,
    csrf_token: str | None,
    *,
    workspace_id: UUID,
    mutation: bool,
) -> ViralService:
    if session_token is None:
        raise HTTPException(status_code=401, detail="invalid session")
    auth = InviteAuthService(session)
    context = auth.authenticate(session_token)
    if context is None:
        raise HTTPException(status_code=401, detail="invalid session")
    if context.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="workspace not found")
    if mutation and (
        csrf_token is None or not auth.validate_csrf(session_token, csrf_token)
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return ViralService(session, context)


@router.put(
    "/v1/workspaces/{workspace_id}/accounts/{account_id}/viral-thresholds",
    response_model=ViralThresholdRead,
)
def configure_viral_thresholds(
    workspace_id: UUID,
    account_id: UUID,
    data: ViralThresholdInput,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> ViralThresholdProfile:
    service = _service(
        session, session_token, csrf_token, workspace_id=workspace_id, mutation=True
    )
    try:
        profile = service.configure_thresholds(account_id, data)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return profile


@router.get(
    "/v1/workspaces/{workspace_id}/accounts/{account_id}/viral-thresholds",
    response_model=ViralThresholdRead | None,
)
def read_viral_thresholds(
    workspace_id: UUID,
    account_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> ViralThresholdProfile | None:
    service = _service(
        session, session_token, None, workspace_id=workspace_id, mutation=False
    )
    try:
        return service.current_threshold(account_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post(
    "/v1/workspaces/{workspace_id}/accounts/{account_id}/viral-candidates/evaluate",
    response_model=list[ViralCandidateRead],
)
def evaluate_viral_candidates(
    workspace_id: UUID,
    account_id: UUID,
    data: ViralEvaluationInput,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> list[ViralCandidateRead]:
    service = _service(
        session, session_token, csrf_token, workspace_id=workspace_id, mutation=True
    )
    try:
        candidates = service.evaluate(account_id, data)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    session.commit()
    return [service.candidate_payload(candidate) for candidate in candidates]


@router.get(
    "/v1/workspaces/{workspace_id}/viral-candidates",
    response_model=list[ViralCandidateRead],
)
def list_viral_candidates(
    workspace_id: UUID,
    account_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[ViralCandidateRead]:
    service = _service(
        session, session_token, None, workspace_id=workspace_id, mutation=False
    )
    try:
        candidates = service.list_candidates(account_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return [service.candidate_payload(candidate) for candidate in candidates]


@router.post(
    "/v1/workspaces/{workspace_id}/viral-candidates/{candidate_id}/confirm",
    response_model=ViralLibraryItemRead,
    status_code=201,
)
def confirm_viral_candidate(
    workspace_id: UUID,
    candidate_id: UUID,
    data: ViralConfirmationInput,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> ViralLibraryItemRead:
    service = _service(
        session, session_token, csrf_token, workspace_id=workspace_id, mutation=True
    )
    try:
        item = service.confirm(candidate_id, data)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    session.commit()
    return service.library_payload(item)


@router.get(
    "/v1/workspaces/{workspace_id}/viral-library",
    response_model=list[ViralLibraryItemRead],
)
def list_viral_library(
    workspace_id: UUID,
    account_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[ViralLibraryItemRead]:
    service = _service(
        session, session_token, None, workspace_id=workspace_id, mutation=False
    )
    try:
        items = service.library_items(account_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return [service.library_payload(item) for item in items]


@router.get(
    "/v1/workspaces/{workspace_id}/viral-library/generation-sources",
    response_model=list[ViralLibraryItemRead],
)
def list_generation_viral_sources(
    workspace_id: UUID,
    account_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[ViralLibraryItemRead]:
    service = _service(
        session, session_token, None, workspace_id=workspace_id, mutation=False
    )
    try:
        items = service.library_items(account_id, active_only=True)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return [service.library_payload(item) for item in items]


@router.post(
    "/v1/workspaces/{workspace_id}/viral-library/{item_id}/revoke",
    response_model=ViralLibraryItemRead,
)
def revoke_viral_library_item(
    workspace_id: UUID,
    item_id: UUID,
    data: ViralRevocationInput,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> ViralLibraryItemRead:
    service = _service(
        session, session_token, csrf_token, workspace_id=workspace_id, mutation=True
    )
    try:
        item = service.revoke(item_id, data)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    session.commit()
    return service.library_payload(item)
