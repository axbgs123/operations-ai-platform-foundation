from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.storage import Storage, get_storage
from app.modules.exports.models import ExportKind, ExportStatus, ExportTask
from app.modules.exports.service import (
    ExportIdempotencyConflict,
    create_export_task,
)
from app.modules.exports.tasks import get_export_enqueuer
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.permissions import Permission, PermissionDenied, require_permission


router = APIRouter(prefix="/v1/workspaces/{workspace_id}/exports", tags=["exports"])
DatabaseSession = Annotated[Session, Depends(get_session)]
ObjectStorage = Annotated[Storage, Depends(get_storage)]


class ExportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["csv", "markdown"]
    content_id: UUID | None = None


class ExportTaskRead(BaseModel):
    id: UUID
    workspace_id: UUID
    kind: Literal["csv", "markdown"]
    content_id: UUID | None
    status: Literal["queued", "running", "succeeded", "failed"]
    file_name: str | None
    mime_type: str | None
    download_url: str | None
    download_expires_at: datetime | None
    error_code: str | None


def _context(
    session: Session,
    workspace_id: UUID,
    session_token: str | None,
    csrf_token: str | None,
    *,
    mutation: bool,
):
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
    try:
        require_permission(context.role, Permission.WRITE_CONTENT)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    return context


def _payload(task: ExportTask, storage: Storage | None = None) -> ExportTaskRead:
    download_url = None
    expires_at = None
    if (
        storage is not None
        and task.status is ExportStatus.SUCCEEDED
        and task.object_key is not None
    ):
        download_url, expires_at = storage.presign_download(task.object_key)
    return ExportTaskRead(
        id=task.id,
        workspace_id=task.workspace_id,
        kind=task.kind.value,
        content_id=task.content_id,
        status=task.status.value,
        file_name=task.file_name,
        mime_type=task.mime_type,
        download_url=download_url,
        download_expires_at=expires_at,
        error_code=task.error_code,
    )


@router.post("", response_model=ExportTaskRead, status_code=202)
def create_export(
    workspace_id: UUID,
    data: ExportCreate,
    session: DatabaseSession,
    enqueuer: Annotated[Callable[[UUID], None], Depends(get_export_enqueuer)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> ExportTaskRead:
    context = _context(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=True,
    )
    try:
        task, created = create_export_task(
            session,
            context,
            kind=ExportKind(data.kind),
            content_id=data.content_id,
            idempotency_key=idempotency_key,
        )
    except ExportIdempotencyConflict as error:
        raise HTTPException(status_code=409, detail="idempotency conflict") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail="content not found") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    if created or (
        task.status is ExportStatus.QUEUED and task.enqueued_at is None
    ):
        try:
            enqueuer(task.id)
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="export queue unavailable",
            ) from error
        task.enqueued_at = datetime.now(UTC)
        session.commit()
    return _payload(task)


@router.get("/{task_id}", response_model=ExportTaskRead)
def read_export(
    workspace_id: UUID,
    task_id: UUID,
    session: DatabaseSession,
    storage: ObjectStorage,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> ExportTaskRead:
    _context(
        session,
        workspace_id,
        session_token,
        None,
        mutation=False,
    )
    task = session.scalar(
        select(ExportTask).where(
            ExportTask.id == task_id,
            ExportTask.workspace_id == workspace_id,
        )
    )
    if task is None:
        raise HTTPException(status_code=404, detail="export not found")
    return _payload(task, storage)
