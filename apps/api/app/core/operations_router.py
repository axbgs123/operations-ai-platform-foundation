from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.health import DependencyStatus, ReadinessService, get_readiness_service
from app.core.logging import current_request_id
from app.core.observability import (
    DeadLetterDiagnostic,
    OperationalTask,
    OperationsService,
    SQLAlchemyOperationsStore,
)
from app.core.security import WorkspaceContext
from app.modules.workspace.auth import InviteAuthService


router = APIRouter(tags=["operations"])
DatabaseSession = Annotated[Session, Depends(get_session)]


class TaskListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[OperationalTask]
    next_offset: int | None
    total: int


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "not_ready"]
    error_code: Literal["DEPENDENCY_NOT_READY"] | None = None
    components: list[DependencyStatus]


class OperationsAccessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["admin", "editor", "viewer", "demo"]
    can_read: bool
    can_operate: bool


def dispatch_operational_retry(task: OperationalTask) -> None:
    """Enqueue the newly-created retry only after its database transaction commits."""
    if task.task_type == "analysis":
        from app.modules.analysis.tasks import enqueue_analysis

        enqueue_analysis(task.task_id)
    elif task.task_type == "generation":
        from app.modules.generation.tasks import enqueue_text_generation

        enqueue_text_generation(task.task_id)
    elif task.task_type == "export":
        from app.modules.exports.tasks import enqueue_export

        enqueue_export(task.task_id)
    elif task.task_type == "restore":
        from app.modules.exports.restore_tasks import enqueue_restore

        enqueue_restore(task.task_id)
    elif task.task_type == "workspace_deletion":
        from app.modules.exports.retention_tasks import enqueue_workspace_deletion

        enqueue_workspace_deletion(task.task_id)
    elif task.task_type == "product_event_outbox":
        # The existing outbox recovery beat safely leases retrying records.
        return


def _context(
    session: Session,
    *,
    workspace_id: UUID,
    session_token: str | None,
    csrf_token: str | None = None,
    mutation: bool,
) -> WorkspaceContext:
    if session_token is None:
        raise HTTPException(status_code=401, detail={"code": "INVALID_SESSION"})
    auth = InviteAuthService(session)
    context = auth.authenticate(session_token)
    if context is None:
        raise HTTPException(status_code=401, detail={"code": "INVALID_SESSION"})
    if context.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
    if mutation and (
        csrf_token is None or not auth.validate_csrf(session_token, csrf_token)
    ):
        raise HTTPException(status_code=403, detail={"code": "CSRF_VALIDATION_FAILED"})
    if context.role not in {"admin", "editor"}:
        raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED"})
    return context


def _service(
    session: Session,
    context: WorkspaceContext,
) -> OperationsService:
    return OperationsService(
        SQLAlchemyOperationsStore(
            session,
            request_id=current_request_id(),
            actor_id=context.member_id,
        )
    )


@router.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "alive"}


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
def readiness(
    response: Response,
    service: Annotated[ReadinessService, Depends(get_readiness_service)],
) -> ReadinessResponse:
    result = service.check()
    if result.status == "not_ready":
        response.status_code = 503
    return ReadinessResponse(
        status=result.status,
        error_code=("DEPENDENCY_NOT_READY" if result.status == "not_ready" else None),
        components=list(result.components),
    )


@router.get(
    "/v1/workspaces/{workspace_id}/operations/tasks",
    response_model=TaskListResponse,
)
def list_tasks(
    workspace_id: UUID,
    session: DatabaseSession,
    task_type: Annotated[str | None, Query(max_length=80)] = None,
    status: Annotated[str | None, Query(max_length=40)] = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> TaskListResponse:
    context = _context(
        session,
        workspace_id=workspace_id,
        session_token=session_token,
        mutation=False,
    )
    tasks = _service(session, context).list_tasks(
        context,
        task_type=task_type,
        status=status,
        created_after=created_after,
        created_before=created_before,
    )
    page = tasks[offset : offset + limit]
    return TaskListResponse(
        items=page,
        total=len(tasks),
        next_offset=offset + limit if offset + limit < len(tasks) else None,
    )


@router.get(
    "/v1/workspaces/{workspace_id}/operations/access",
    response_model=OperationsAccessResponse,
)
def read_operations_access(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> OperationsAccessResponse:
    if session_token is None:
        raise HTTPException(status_code=401, detail={"code": "INVALID_SESSION"})
    context = InviteAuthService(session).authenticate(session_token)
    if context is None:
        raise HTTPException(status_code=401, detail={"code": "INVALID_SESSION"})
    if context.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
    return OperationsAccessResponse(
        role=context.role,
        can_read=context.role in {"admin", "editor"},
        can_operate=context.role == "admin",
    )


@router.get(
    "/v1/workspaces/{workspace_id}/operations/tasks/{task_type}/{task_id}",
    response_model=OperationalTask,
)
def read_task(
    workspace_id: UUID,
    task_type: str,
    task_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> OperationalTask:
    context = _context(
        session,
        workspace_id=workspace_id,
        session_token=session_token,
        mutation=False,
    )
    try:
        return _service(session, context).read_task(context, task_type, task_id)
    except LookupError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "TASK_NOT_FOUND"},
        ) from error


def _mutation(
    *,
    action: Literal["cancel", "retry"],
    workspace_id: UUID,
    task_type: str,
    task_id: UUID,
    session: Session,
    idempotency_key: str,
    session_token: str | None,
    csrf_token: str | None,
) -> OperationalTask:
    context = _context(
        session,
        workspace_id=workspace_id,
        session_token=session_token,
        csrf_token=csrf_token,
        mutation=True,
    )
    if context.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED"})
    try:
        service = _service(session, context)
        result = (
            service.cancel(
                context,
                task_type=task_type,
                task_id=task_id,
                idempotency_key=idempotency_key,
            )
            if action == "cancel"
            else service.retry(
                context,
                task_type=task_type,
                task_id=task_id,
                idempotency_key=idempotency_key,
            )
        )
        session.commit()
        return result
    except LookupError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "TASK_NOT_FOUND"},
        ) from error
    except ValueError as error:
        session.rollback()
        code = str(error)
        raise HTTPException(status_code=409, detail={"code": code}) from error


@router.post(
    "/v1/workspaces/{workspace_id}/operations/tasks/{task_type}/{task_id}/cancel",
    response_model=OperationalTask,
)
def cancel_task(
    workspace_id: UUID,
    task_type: str,
    task_id: UUID,
    session: DatabaseSession,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=200),
    ],
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> OperationalTask:
    return _mutation(
        action="cancel",
        workspace_id=workspace_id,
        task_type=task_type,
        task_id=task_id,
        session=session,
        idempotency_key=idempotency_key,
        session_token=session_token,
        csrf_token=csrf_token,
    )


@router.post(
    "/v1/workspaces/{workspace_id}/operations/tasks/{task_type}/{task_id}/retry",
    response_model=OperationalTask,
)
def retry_task(
    workspace_id: UUID,
    task_type: str,
    task_id: UUID,
    session: DatabaseSession,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=200),
    ],
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> OperationalTask:
    result = _mutation(
        action="retry",
        workspace_id=workspace_id,
        task_type=task_type,
        task_id=task_id,
        session=session,
        idempotency_key=idempotency_key,
        session_token=session_token,
        csrf_token=csrf_token,
    )
    dispatch_operational_retry(result)
    return result


@router.get(
    "/v1/workspaces/{workspace_id}/operations/tasks/{task_type}/{task_id}/diagnostic",
    response_model=DeadLetterDiagnostic,
)
def read_task_diagnostic(
    workspace_id: UUID,
    task_type: str,
    task_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> DeadLetterDiagnostic:
    context = _context(
        session,
        workspace_id=workspace_id,
        session_token=session_token,
        mutation=False,
    )
    if context.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED"})
    try:
        return _service(session, context).safe_diagnostic(
            context,
            task_type,
            task_id,
        )
    except LookupError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "TASK_NOT_FOUND"},
        ) from error
