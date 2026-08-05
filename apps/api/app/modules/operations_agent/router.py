from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.security import WorkspaceContext
from app.modules.operations_agent.briefing import BriefingService
from app.modules.operations_agent.planning import (
    AgentApprovalStale,
    InvalidAgentPlan,
    PlanService,
)
from app.modules.operations_agent.schemas import (
    AgentPlanCreate,
    AgentPlanRead,
    BriefingDecisionCreate,
    DailyBriefingRead,
)
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.permissions import (
    Permission,
    PermissionDenied,
    require_permission,
)


router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/agent",
    tags=["operations-agent"],
)
DatabaseSession = Annotated[Session, Depends(get_session)]
IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=200),
]


def _authorized_context(
    session: Session,
    *,
    workspace_id: UUID,
    session_token: str | None,
    csrf_token: str | None,
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
    if context.role == "demo":
        raise HTTPException(
            status_code=403,
            detail="private operations agent unavailable",
        )
    if mutation and (
        csrf_token is None
        or not auth.validate_csrf(session_token, csrf_token)
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    try:
        require_permission(
            context.role,
            Permission.WRITE_CONTENT if mutation else Permission.READ_CONTENT,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    return context


def _service(
    session: Session,
    *,
    workspace_id: UUID,
    session_token: str | None,
    csrf_token: str | None,
    mutation: bool,
) -> BriefingService:
    return BriefingService(
        session,
        _authorized_context(
            session,
            workspace_id=workspace_id,
            session_token=session_token,
            csrf_token=csrf_token,
            mutation=mutation,
        ),
    )


@router.get("/briefing", response_model=DailyBriefingRead)
def read_briefing(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[
        str | None,
        Cookie(alias="session"),
    ] = None,
) -> DailyBriefingRead:
    service = _service(
        session,
        workspace_id=workspace_id,
        session_token=session_token,
        csrf_token=None,
        mutation=False,
    )
    try:
        briefing = service.generate()
    except LookupError as error:
        raise HTTPException(
            status_code=404,
            detail="workspace not found",
        ) from error
    session.commit()
    return briefing


@router.post("/briefing/refresh", response_model=DailyBriefingRead)
def refresh_briefing(
    workspace_id: UUID,
    idempotency_key: IdempotencyKey,
    session: DatabaseSession,
    session_token: Annotated[
        str | None,
        Cookie(alias="session"),
    ] = None,
    csrf_token: Annotated[
        str | None,
        Header(alias="X-CSRF-Token"),
    ] = None,
) -> DailyBriefingRead:
    service = _service(
        session,
        workspace_id=workspace_id,
        session_token=session_token,
        csrf_token=csrf_token,
        mutation=True,
    )
    try:
        briefing = service.record_refresh(
            idempotency_key=idempotency_key,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    session.commit()
    return briefing


@router.post(
    "/briefings/{briefing_id}/decisions",
    response_model=DailyBriefingRead,
)
def record_briefing_decision(
    workspace_id: UUID,
    briefing_id: UUID,
    data: BriefingDecisionCreate,
    idempotency_key: IdempotencyKey,
    session: DatabaseSession,
    session_token: Annotated[
        str | None,
        Cookie(alias="session"),
    ] = None,
    csrf_token: Annotated[
        str | None,
        Header(alias="X-CSRF-Token"),
    ] = None,
) -> DailyBriefingRead:
    service = _service(
        session,
        workspace_id=workspace_id,
        session_token=session_token,
        csrf_token=csrf_token,
        mutation=True,
    )
    try:
        briefing = service.record_decision(
            briefing_id,
            decision=data.decision,
            candidate_kind=data.candidate_kind,
            idempotency_key=idempotency_key,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail="briefing not found") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    session.commit()
    return briefing


def _plan_service(
    session: Session,
    *,
    workspace_id: UUID,
    session_token: str | None,
    csrf_token: str | None,
    mutation: bool,
) -> PlanService:
    return PlanService(
        session,
        _authorized_context(
            session,
            workspace_id=workspace_id,
            session_token=session_token,
            csrf_token=csrf_token,
            mutation=mutation,
        ),
    )


@router.post("/plans", response_model=AgentPlanRead, status_code=201)
def create_plan(
    workspace_id: UUID,
    data: AgentPlanCreate,
    idempotency_key: IdempotencyKey,
    session: DatabaseSession,
    session_token: Annotated[
        str | None,
        Cookie(alias="session"),
    ] = None,
    csrf_token: Annotated[
        str | None,
        Header(alias="X-CSRF-Token"),
    ] = None,
) -> AgentPlanRead:
    service = _plan_service(
        session,
        workspace_id=workspace_id,
        session_token=session_token,
        csrf_token=csrf_token,
        mutation=True,
    )
    try:
        plan = service.create(data, idempotency_key=idempotency_key)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except AgentApprovalStale as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (InvalidAgentPlan, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    session.commit()
    return plan


@router.get("/plans/{plan_id}", response_model=AgentPlanRead)
def read_plan(
    workspace_id: UUID,
    plan_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[
        str | None,
        Cookie(alias="session"),
    ] = None,
) -> AgentPlanRead:
    service = _plan_service(
        session,
        workspace_id=workspace_id,
        session_token=session_token,
        csrf_token=None,
        mutation=False,
    )
    try:
        return service.get(plan_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="plan not found") from error


@router.post("/plans/{plan_id}/approve", response_model=AgentPlanRead)
def approve_plan(
    workspace_id: UUID,
    plan_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[
        str | None,
        Cookie(alias="session"),
    ] = None,
    csrf_token: Annotated[
        str | None,
        Header(alias="X-CSRF-Token"),
    ] = None,
) -> AgentPlanRead:
    service = _plan_service(
        session,
        workspace_id=workspace_id,
        session_token=session_token,
        csrf_token=csrf_token,
        mutation=True,
    )
    try:
        plan = service.approve(plan_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="plan not found") from error
    except AgentApprovalStale as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    session.commit()
    return plan


@router.post("/plans/{plan_id}/reject", response_model=AgentPlanRead)
def reject_plan(
    workspace_id: UUID,
    plan_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[
        str | None,
        Cookie(alias="session"),
    ] = None,
    csrf_token: Annotated[
        str | None,
        Header(alias="X-CSRF-Token"),
    ] = None,
) -> AgentPlanRead:
    service = _plan_service(
        session,
        workspace_id=workspace_id,
        session_token=session_token,
        csrf_token=csrf_token,
        mutation=True,
    )
    try:
        plan = service.reject(plan_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="plan not found") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    session.commit()
    return plan
