import hashlib
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from fastapi import APIRouter, Body, Cookie, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_session, uuid7
from app.core.security import WorkspaceContext
from app.modules.content.models import DeletedItem
from app.modules.exports.deletion import (
    ResourcePurgeExpired,
    RetentionService,
    RetentionStrategy,
    TrashService,
    WorkspaceDeletionBlocked,
    WorkspaceDeletionImpact,
    WorkspaceDeletionService,
)
from app.modules.exports.models import (
    RetentionPolicy,
    WorkspaceDeletionJob,
)
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.models import (
    MemberRole,
    WorkspaceMember,
    WorkspaceSession,
)
from app.modules.workspace.permissions import PermissionDenied


router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}",
    tags=["deletion"],
)
DatabaseSession = Annotated[Session, Depends(get_session)]
T = TypeVar("T")


class ResponseMeta(BaseModel):
    request_id: UUID
    task_id: UUID | None = None


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: ResponseMeta
    error: None = None


class TrashDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=240)


class TrashItemRead(BaseModel):
    id: UUID
    resource_type: str
    resource_id: UUID
    deleted_by: UUID | None
    deleted_at: datetime
    scheduled_purge_at: datetime
    deletion_reason: str | None
    status: str
    restored_at: datetime | None


class RestoredContentRead(BaseModel):
    id: UUID
    workspace_id: UUID
    platform: str
    deleted_at: datetime | None


class RetentionPolicyWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy: Literal["immediate", "scheduled", "evidence"]
    retention_seconds: int | None = Field(default=None, ge=1)


class RetentionPolicyRead(BaseModel):
    version: int
    strategy: str
    retention_seconds: int | None
    effective_at: datetime


class ConfirmationRead(BaseModel):
    confirmation_token: str
    expires_at: datetime
    impact: WorkspaceDeletionImpact


class DeletionConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation_token: str = Field(min_length=20, max_length=200)


class DeletionJobRead(BaseModel):
    id: UUID
    workspace_id: UUID
    status: str
    phase: str
    error_code: str | None
    inventory: dict[str, object]
    completed_at: datetime | None


def get_deletion_enqueuer() -> Callable[[UUID], None]:
    from app.modules.exports.retention_tasks import enqueue_workspace_deletion

    return enqueue_workspace_deletion


def _meta(task_id: UUID | None = None) -> ResponseMeta:
    return ResponseMeta(request_id=uuid7(), task_id=task_id)


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


def _trash_payload(item: DeletedItem) -> TrashItemRead:
    return TrashItemRead(
        id=item.id,
        resource_type=item.resource_type,
        resource_id=item.resource_id,
        deleted_by=item.deleted_by,
        deleted_at=item.deleted_at,
        scheduled_purge_at=item.scheduled_purge_at,
        deletion_reason=item.deletion_reason,
        status=item.status.value,
        restored_at=item.restored_at,
    )


def _retention_payload(policy: RetentionPolicy) -> RetentionPolicyRead:
    return RetentionPolicyRead(
        version=policy.version,
        strategy=policy.strategy.value,
        retention_seconds=policy.retention_seconds,
        effective_at=policy.effective_at,
    )


def _job_payload(job: WorkspaceDeletionJob) -> DeletionJobRead:
    safe_inventory = {
        key: value
        for key, value in job.inventory.items()
        if key != "object_keys"
    }
    return DeletionJobRead(
        id=job.id,
        workspace_id=job.workspace_id,
        status=job.status.value,
        phase=job.phase.value,
        error_code=job.error_code,
        inventory=safe_inventory,
        completed_at=job.completed_at,
    )


@router.get("/trash", response_model=Envelope[list[TrashItemRead]])
def list_trash(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> Envelope[list[TrashItemRead]]:
    context = _context(
        session, workspace_id, session_token, None, mutation=False
    )
    try:
        items = TrashService(session, context).list_items()
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    return Envelope(
        data=[_trash_payload(item) for item in items],
        meta=_meta(),
    )


@router.post(
    "/trash/contents/{content_id}",
    response_model=Envelope[TrashItemRead],
)
def soft_delete_content(
    workspace_id: UUID,
    content_id: UUID,
    session: DatabaseSession,
    data: Annotated[TrashDeleteRequest, Body()] = TrashDeleteRequest(),
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> Envelope[TrashItemRead]:
    context = _context(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=True,
    )
    try:
        item = TrashService(session, context).soft_delete_content(
            content_id,
            reason=data.reason,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail="content not found") from error
    session.commit()
    return Envelope(data=_trash_payload(item), meta=_meta())


@router.post(
    "/trash/contents/{content_id}/restore",
    response_model=Envelope[RestoredContentRead],
)
def restore_content(
    workspace_id: UUID,
    content_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> Envelope[RestoredContentRead]:
    context = _context(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=True,
    )
    try:
        content = TrashService(session, context).restore_content(content_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail="content not found") from error
    except ResourcePurgeExpired as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "RESOURCE_PURGE_EXPIRED"},
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "RESOURCE_ALREADY_DELETED"},
        ) from error
    session.commit()
    return Envelope(
        data=RestoredContentRead(
            id=content.id,
            workspace_id=content.workspace_id,
            platform=content.platform.value,
            deleted_at=content.deleted_at,
        ),
        meta=_meta(),
    )


@router.get(
    "/retention-policy",
    response_model=Envelope[RetentionPolicyRead],
)
def read_retention_policy(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> Envelope[RetentionPolicyRead]:
    context = _context(
        session, workspace_id, session_token, None, mutation=False
    )
    policy = RetentionService(session, context).current_policy()
    if policy is None:
        raise HTTPException(status_code=404, detail="retention policy not found")
    return Envelope(data=_retention_payload(policy), meta=_meta())


@router.put(
    "/retention-policy",
    response_model=Envelope[RetentionPolicyRead],
)
def configure_retention_policy(
    workspace_id: UUID,
    data: RetentionPolicyWrite,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> Envelope[RetentionPolicyRead]:
    context = _context(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=True,
    )
    try:
        policy = RetentionService(session, context).configure(
            strategy=RetentionStrategy(data.strategy),
            retention_seconds=data.retention_seconds,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "RETENTION_POLICY_CONFLICT"},
        ) from error
    session.commit()
    return Envelope(data=_retention_payload(policy), meta=_meta())


@router.get(
    "/deletion-impact",
    response_model=Envelope[WorkspaceDeletionImpact],
)
def deletion_impact(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> Envelope[WorkspaceDeletionImpact]:
    context = _context(
        session, workspace_id, session_token, None, mutation=False
    )
    try:
        impact = WorkspaceDeletionService(session, context).impact()
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    return Envelope(data=impact, meta=_meta())


@router.post(
    "/deletion-confirmations",
    response_model=Envelope[ConfirmationRead],
    status_code=201,
)
def request_deletion_confirmation(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> Envelope[ConfirmationRead]:
    context = _context(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=True,
    )
    service = WorkspaceDeletionService(session, context)
    try:
        impact = service.impact()
        token, confirmation = service.request_confirmation()
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except WorkspaceDeletionBlocked as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "WORKSPACE_DELETION_BLOCKED"},
        ) from error
    session.commit()
    return Envelope(
        data=ConfirmationRead(
            confirmation_token=token,
            expires_at=confirmation.expires_at,
            impact=impact,
        ),
        meta=_meta(),
    )


@router.post(
    "/deletions",
    response_model=Envelope[DeletionJobRead],
    status_code=202,
)
def confirm_workspace_deletion(
    workspace_id: UUID,
    data: DeletionConfirmRequest,
    session: DatabaseSession,
    enqueuer: Annotated[
        Callable[[UUID], None],
        Depends(get_deletion_enqueuer),
    ],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> Envelope[DeletionJobRead]:
    context = _context(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=True,
    )
    try:
        job, created = WorkspaceDeletionService(
            session, context
        ).confirm_deletion(
            data.confirmation_token,
            idempotency_key=idempotency_key,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except WorkspaceDeletionBlocked as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "WORKSPACE_DELETION_BLOCKED"},
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "DELETION_CONFIRMATION_INVALID"},
        ) from error
    session.commit()
    if created:
        try:
            enqueuer(job.id)
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="deletion queue unavailable",
            ) from error
    return Envelope(data=_job_payload(job), meta=_meta(job.id))


@router.get(
    "/deletions/{job_id}",
    response_model=Envelope[DeletionJobRead],
)
def read_workspace_deletion(
    workspace_id: UUID,
    job_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> Envelope[DeletionJobRead]:
    if session_token is None:
        raise HTTPException(status_code=401, detail="invalid session")
    token_hash = hashlib.sha256(session_token.encode()).hexdigest()
    stored_session = session.scalar(
        select(WorkspaceSession).where(
            WorkspaceSession.token_hash == token_hash,
            WorkspaceSession.workspace_id == workspace_id,
        )
    )
    job = session.scalar(
        select(WorkspaceDeletionJob).where(
            WorkspaceDeletionJob.id == job_id,
            WorkspaceDeletionJob.workspace_id == workspace_id,
        )
    )
    if stored_session is None or job is None:
        raise HTTPException(status_code=404, detail="deletion task not found")
    member = session.get(WorkspaceMember, stored_session.member_id)
    if (
        member is None
        or member.id != job.requested_by
        or member.role is not MemberRole.ADMIN
    ):
        raise HTTPException(status_code=404, detail="deletion task not found")
    return Envelope(data=_job_payload(job), meta=_meta(job.id))
