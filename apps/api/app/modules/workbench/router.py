from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.modules.content.account_models import Platform
from app.modules.workbench.schemas import (
    AnalysisQueueRead,
    PreflightQueueRead,
    WorkbenchContextRead,
    WorkbenchOverviewRead,
)
from app.modules.workbench.service import WorkbenchService
from app.modules.workspace.auth import InviteAuthService


router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/workbench",
    tags=["workbench"],
)
DatabaseSession = Annotated[Session, Depends(get_session)]
PlatformQuery = Annotated[
    Literal["douyin", "xiaohongshu"],
    Query(),
]


def _service(
    session: Session,
    workspace_id: UUID,
    session_token: str | None,
) -> WorkbenchService:
    if session_token is None:
        raise HTTPException(status_code=401, detail="invalid session")
    context = InviteAuthService(session).authenticate(session_token)
    if context is None:
        raise HTTPException(status_code=401, detail="invalid session")
    if context.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="workspace not found")
    if context.role == "demo":
        raise HTTPException(
            status_code=403,
            detail="private workbench unavailable",
        )
    return WorkbenchService(session, context)


@router.get("/context", response_model=WorkbenchContextRead)
def read_workbench_context(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[
        str | None,
        Cookie(alias="session"),
    ] = None,
) -> WorkbenchContextRead:
    service = _service(session, workspace_id, session_token)
    try:
        return service.context()
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(
            status_code=404,
            detail="workspace not found",
        ) from error


@router.get("/overview", response_model=WorkbenchOverviewRead)
def read_workbench_overview(
    workspace_id: UUID,
    session: DatabaseSession,
    platform: Annotated[Literal["douyin", "xiaohongshu"] | None, Query()] = None,
    account_id: Annotated[UUID | None, Query()] = None,
    session_token: Annotated[
        str | None,
        Cookie(alias="session"),
    ] = None,
) -> WorkbenchOverviewRead:
    service = _service(session, workspace_id, session_token)
    try:
        return service.overview(
            Platform(platform) if platform is not None else None,
            account_id=account_id,
        )
    except LookupError as error:
        raise HTTPException(
            status_code=404,
            detail="account not found",
        ) from error


@router.get("/analysis-queue", response_model=AnalysisQueueRead)
def read_analysis_queue(
    workspace_id: UUID,
    platform: PlatformQuery,
    session: DatabaseSession,
    account_id: Annotated[UUID | None, Query()] = None,
    session_token: Annotated[
        str | None,
        Cookie(alias="session"),
    ] = None,
) -> AnalysisQueueRead:
    service = _service(session, workspace_id, session_token)
    try:
        return service.analysis_queue(
            Platform(platform),
            account_id=account_id,
        )
    except LookupError as error:
        raise HTTPException(
            status_code=404,
            detail="account not found",
        ) from error


@router.get("/preflight-queue", response_model=PreflightQueueRead)
def read_preflight_queue(
    workspace_id: UUID,
    platform: PlatformQuery,
    session: DatabaseSession,
    account_id: Annotated[UUID | None, Query()] = None,
    session_token: Annotated[
        str | None,
        Cookie(alias="session"),
    ] = None,
) -> PreflightQueueRead:
    service = _service(session, workspace_id, session_token)
    try:
        return service.preflight_queue(
            Platform(platform),
            account_id=account_id,
        )
    except LookupError as error:
        raise HTTPException(
            status_code=404,
            detail="account not found",
        ) from error
