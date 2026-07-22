from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.modules.analysis.schemas import (
    AnalysisFeedbackInput,
    AnalysisRunRead,
    AnalysisSettingInput,
    AnalysisSettingRead,
    AnalysisSuggestionRead,
    ProductEventAck,
    SuggestionAdoptionInput,
)
from app.modules.analysis.service import AnalysisService
from app.modules.analysis.tasks import get_analysis_enqueuer
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.permissions import PermissionDenied


router = APIRouter(tags=["analysis"])
DatabaseSession = Annotated[Session, Depends(get_session)]


def _service(session, session_token, csrf_token, *, mutation, workspace_id=None):
    if session_token is None:
        raise HTTPException(status_code=401, detail="invalid session")
    auth = InviteAuthService(session)
    context = auth.authenticate(session_token)
    if context is None:
        raise HTTPException(status_code=401, detail="invalid session")
    if workspace_id is not None and context.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="workspace not found")
    if mutation and (csrf_token is None or not auth.validate_csrf(session_token, csrf_token)):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return AnalysisService(session, context)


@router.post("/v1/contents/{content_id}/analysis-runs", response_model=AnalysisRunRead, status_code=202)
def request_analysis(
    content_id: UUID,
    background_tasks: BackgroundTasks,
    session: DatabaseSession,
    enqueuer: Annotated[Callable[[UUID], None], Depends(get_analysis_enqueuer)],
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
):
    service = _service(session, session_token, csrf_token, mutation=True)
    try:
        run, should_enqueue = service.request(content_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    if should_enqueue:
        background_tasks.add_task(enqueuer, run.id)
    return run


@router.get("/v1/contents/{content_id}/analysis-runs/{run_id}", response_model=AnalysisRunRead)
def read_analysis(
    content_id: UUID,
    run_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
):
    service = _service(session, session_token, None, mutation=False)
    try:
        return service.read(content_id, run_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/v1/workspaces/{workspace_id}/accounts/{account_id}/analysis-settings", response_model=AnalysisSettingRead)
def read_analysis_setting(
    workspace_id: UUID,
    account_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
):
    service = _service(session, session_token, None, mutation=False, workspace_id=workspace_id)
    try:
        setting = service.setting(account_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"auto_analyze": setting.auto_analyze if setting else False}


@router.put("/v1/workspaces/{workspace_id}/accounts/{account_id}/analysis-settings", response_model=AnalysisSettingRead)
def update_analysis_setting(
    workspace_id: UUID,
    account_id: UUID,
    data: AnalysisSettingInput,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
):
    service = _service(session, session_token, csrf_token, mutation=True, workspace_id=workspace_id)
    try:
        setting = service.update_setting(account_id, data.auto_analyze)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    session.commit()
    return setting


@router.post(
    "/v1/contents/{content_id}/analysis-runs/{run_id}/feedback",
    response_model=ProductEventAck,
    status_code=201,
)
def create_analysis_feedback(
    content_id: UUID,
    run_id: UUID,
    data: AnalysisFeedbackInput,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
):
    service = _service(session, session_token, csrf_token, mutation=True)
    try:
        event = service.feedback(content_id, run_id, data.rating)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    session.commit()
    return event


@router.post(
    "/v1/contents/{content_id}/analysis-runs/{run_id}/suggestions/{recommendation_id}",
    response_model=AnalysisSuggestionRead,
    status_code=201,
)
def save_analysis_suggestion(
    content_id: UUID,
    run_id: UUID,
    recommendation_id: str,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
):
    service = _service(session, session_token, csrf_token, mutation=True)
    try:
        suggestion = service.save_suggestion(content_id, run_id, recommendation_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    session.commit()
    return suggestion


@router.patch(
    "/v1/contents/{content_id}/analysis-suggestions/{suggestion_id}",
    response_model=AnalysisSuggestionRead,
)
def update_analysis_suggestion(
    content_id: UUID,
    suggestion_id: UUID,
    data: SuggestionAdoptionInput,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
):
    service = _service(session, session_token, csrf_token, mutation=True)
    try:
        suggestion = service.adopt_suggestion(
            content_id,
            suggestion_id,
            data.adoption_status,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    session.commit()
    return suggestion
