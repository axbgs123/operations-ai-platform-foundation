from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.core.database import get_session
from app.core.security import WorkspaceContext
from app.modules.operations_agent.briefing import BriefingService
from app.modules.models.models import ModelConfig, ModelUsageAttempt
from app.modules.operations_agent.executor import (
    AgentConfirmationStale,
    AgentExecutor,
)
from app.modules.operations_agent.models import (
    AgentArtifact,
    AgentConfirmation,
    AgentRun,
    AgentRunStep,
    AgentToolRisk,
)
from app.modules.operations_agent.planning import (
    AgentApprovalStale,
    InvalidAgentPlan,
    PlanService,
    build_planning_registry,
)
from app.modules.operations_agent.schemas import (
    AgentPlanCreate,
    AgentPlanRead,
    AgentConfirmationDecision,
    AgentConfirmationListRead,
    AgentConfirmationRead,
    AgentRunListRead,
    AgentRunRead,
    AgentRunStepRead,
    AgentUsageRead,
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


def _enqueue_run(run_id: UUID) -> None:
    from app.modules.operations_agent.tasks import execute_run

    execute_run.delay(str(run_id))


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


@router.post(
    "/plans/{plan_id}/runs",
    response_model=AgentRunRead,
    status_code=201,
)
def start_plan_run(
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
) -> AgentRunRead:
    context = _authorized_context(
        session,
        workspace_id=workspace_id,
        session_token=session_token,
        csrf_token=csrf_token,
        mutation=True,
    )
    existing = session.scalar(
        select(AgentRun).where(
            AgentRun.workspace_id == workspace_id,
            AgentRun.plan_id == plan_id,
        )
    )
    if existing is not None:
        return _run_read(session, existing, include_steps=True)
    try:
        run = _run_executor(session).create_run(
            plan_id,
            context=context,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail="plan not found") from error
    except AgentApprovalStale as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    _enqueue_run(run.id)
    return _run_read(session, run, include_steps=True)


def _run_read(
    session: Session,
    run: AgentRun,
    *,
    include_steps: bool,
) -> AgentRunRead:
    step_records = tuple(
        session.scalars(
            select(AgentRunStep)
            .where(AgentRunStep.run_id == run.id)
            .order_by(AgentRunStep.step_index)
        )
    )
    steps = tuple(
        AgentRunStepRead(
            id=step.id,
            step_index=step.step_index,
            tool_name=step.tool_name,
            tool_version=step.tool_version,
            tool_risk=step.tool_risk,
            status=step.status,
            attempt_count=step.attempt_count,
            safe_summary=(
                str(step.result_envelope.get("safe_summary"))
                if step.result_envelope
                and isinstance(step.result_envelope.get("safe_summary"), str)
                else None
            ),
            safe_error_code=step.safe_error_code,
            started_at=step.started_at,
            completed_at=step.completed_at,
        )
        for step in (step_records if include_steps else ())
    )
    return AgentRunRead(
        id=run.id,
        workspace_id=run.workspace_id,
        plan_id=run.plan_id,
        account_id=run.account_id,
        platform=run.platform,
        status=run.status,
        current_step_index=run.current_step_index,
        safe_error_code=run.safe_error_code,
        created_at=run.created_at,
        updated_at=run.updated_at,
        completed_at=run.completed_at,
        steps=steps,
        usage=_run_usage(session, run, step_records),
    )


def _run_usage(
    session: Session,
    run: AgentRun,
    steps: tuple[AgentRunStep, ...],
) -> AgentUsageRead:
    registry = build_planning_registry()
    uses_external_api = any(
        registry.get(
            step.tool_name,
            version=step.tool_version,
        ).uses_external_api
        for step in steps
    )
    resource_ids = tuple(
        session.scalars(
            select(AgentArtifact.resource_id).where(
                AgentArtifact.workspace_id == run.workspace_id,
                AgentArtifact.run_id == run.id,
            )
        )
    )
    attempts = (
        list(
            session.scalars(
                select(ModelUsageAttempt)
                .where(
                    ModelUsageAttempt.workspace_id == run.workspace_id,
                    ModelUsageAttempt.task_id.in_(resource_ids),
                )
                .order_by(ModelUsageAttempt.created_at, ModelUsageAttempt.id)
            )
        )
        if resource_ids
        else []
    )
    provider = attempts[-1].provider if attempts else None
    model_id = attempts[-1].model_id if attempts else None
    if uses_external_api and provider is None:
        configs = list(
            session.scalars(
                select(ModelConfig)
                .where(ModelConfig.workspace_id == run.workspace_id)
                .order_by(ModelConfig.updated_at.desc(), ModelConfig.id)
            )
        )
        config = next(
            (item for item in configs if "text" in item.capabilities),
            None,
        )
        if config is not None:
            provider = config.provider
            model_id = config.model_id
    return AgentUsageRead(
        uses_external_api=uses_external_api,
        provider=provider,
        model_id=model_id,
        attempt_count=len(attempts),
        input_tokens=sum(item.input_tokens for item in attempts),
        output_tokens=sum(item.output_tokens for item in attempts),
        embedding_tokens=sum(item.embedding_inputs for item in attempts),
        ocr_images=sum(
            item.image_inputs
            for item in attempts
            if item.capability in {"vision", "ocr"}
        ),
        generated_images=sum(item.image_outputs for item in attempts),
        usage_status=(
            attempts[-1].status.value if attempts else "not_used"
        ),
    )


def _confirmation_read(
    confirmation: AgentConfirmation,
) -> AgentConfirmationRead:
    summary = confirmation.action_summary
    raw_argument_keys = summary.get("argument_keys", [])
    argument_keys = (
        tuple(str(item) for item in raw_argument_keys)
        if isinstance(raw_argument_keys, list)
        else ()
    )
    return AgentConfirmationRead(
        id=confirmation.id,
        run_id=confirmation.run_id,
        step_id=confirmation.step_id,
        status=confirmation.status,
        action_fingerprint=confirmation.action_fingerprint,
        tool_name=str(summary["tool_name"]),
        tool_version=str(summary["tool_version"]),
        risk=AgentToolRisk(str(summary["risk"])),
        argument_keys=argument_keys,
        expires_at=confirmation.expires_at,
        resolved_at=confirmation.resolved_at,
        created_at=confirmation.created_at,
    )


def _run_executor(session: Session) -> AgentExecutor:
    return AgentExecutor(
        sessionmaker(bind=session.get_bind(), expire_on_commit=False),
        registry=build_planning_registry(),
    )


@router.get(
    "/confirmations",
    response_model=AgentConfirmationListRead,
)
def list_confirmations(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[
        str | None,
        Cookie(alias="session"),
    ] = None,
) -> AgentConfirmationListRead:
    context = _authorized_context(
        session,
        workspace_id=workspace_id,
        session_token=session_token,
        csrf_token=None,
        mutation=False,
    )
    confirmations = tuple(
        session.scalars(
            select(AgentConfirmation)
            .where(
                AgentConfirmation.workspace_id == workspace_id,
                AgentConfirmation.requested_by == context.member_id,
            )
            .order_by(
                AgentConfirmation.created_at.desc(),
                AgentConfirmation.id.desc(),
            )
        )
    )
    return AgentConfirmationListRead(
        items=tuple(_confirmation_read(item) for item in confirmations)
    )


@router.post(
    "/runs/{run_id}/confirmations",
    response_model=AgentConfirmationRead,
)
def decide_confirmation(
    workspace_id: UUID,
    run_id: UUID,
    data: AgentConfirmationDecision,
    session: DatabaseSession,
    session_token: Annotated[
        str | None,
        Cookie(alias="session"),
    ] = None,
    csrf_token: Annotated[
        str | None,
        Header(alias="X-CSRF-Token"),
    ] = None,
) -> AgentConfirmationRead:
    context = _authorized_context(
        session,
        workspace_id=workspace_id,
        session_token=session_token,
        csrf_token=csrf_token,
        mutation=True,
    )
    try:
        confirmation = _run_executor(session).decide_confirmation(
            run_id,
            confirmation_id=data.confirmation_id,
            decision=data.decision,
            action_fingerprint=data.action_fingerprint,
            context=context,
        )
    except LookupError as error:
        raise HTTPException(
            status_code=404,
            detail="confirmation not found",
        ) from error
    except AgentConfirmationStale as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _confirmation_read(confirmation)


@router.get("/runs", response_model=AgentRunListRead)
def list_runs(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[
        str | None,
        Cookie(alias="session"),
    ] = None,
) -> AgentRunListRead:
    _authorized_context(
        session,
        workspace_id=workspace_id,
        session_token=session_token,
        csrf_token=None,
        mutation=False,
    )
    runs = tuple(
        session.scalars(
            select(AgentRun)
            .where(AgentRun.workspace_id == workspace_id)
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        )
    )
    return AgentRunListRead(
        items=tuple(
            _run_read(session, run, include_steps=False)
            for run in runs
        )
    )


@router.get("/runs/{run_id}", response_model=AgentRunRead)
def read_run(
    workspace_id: UUID,
    run_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[
        str | None,
        Cookie(alias="session"),
    ] = None,
) -> AgentRunRead:
    _authorized_context(
        session,
        workspace_id=workspace_id,
        session_token=session_token,
        csrf_token=None,
        mutation=False,
    )
    run = session.scalar(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.workspace_id == workspace_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _run_read(session, run, include_steps=True)


@router.post("/runs/{run_id}/cancel", response_model=AgentRunRead)
def cancel_run(
    workspace_id: UUID,
    run_id: UUID,
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
) -> AgentRunRead:
    context = _authorized_context(
        session,
        workspace_id=workspace_id,
        session_token=session_token,
        csrf_token=csrf_token,
        mutation=True,
    )
    try:
        _run_executor(session).cancel(
            run_id,
            context=context,
            idempotency_key=idempotency_key,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail="run not found") from error
    session.expire_all()
    run = session.scalar(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.workspace_id == workspace_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _run_read(session, run, include_steps=True)


@router.post("/runs/{run_id}/retry", response_model=AgentRunRead)
def retry_run(
    workspace_id: UUID,
    run_id: UUID,
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
) -> AgentRunRead:
    context = _authorized_context(
        session,
        workspace_id=workspace_id,
        session_token=session_token,
        csrf_token=csrf_token,
        mutation=True,
    )
    try:
        _run_executor(session).retry(
            run_id,
            context=context,
            idempotency_key=idempotency_key,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail="run not found") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    session.expire_all()
    run = session.scalar(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.workspace_id == workspace_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _run_read(session, run, include_steps=True)
