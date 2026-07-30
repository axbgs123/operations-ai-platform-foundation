from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    UploadFile,
)
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.storage import Storage, get_storage
from app.modules.exports.models import ExportKind, ExportStatus, ExportTask
from app.modules.exports.models import (
    FullRestorePhase,
    FullRestoreStatus,
    KnowledgeIndexRebuild,
    RestoreJob,
)
from app.modules.exports.manifest import (
    MAX_BACKUP_BYTES,
    BackupFormatError,
    parse_manifest_json,
)
from app.modules.exports.restore_preview import (
    RestoreMode,
    RestorePreview,
    build_restore_preview,
)
from app.modules.exports.zip_restore import (
    ArchiveLimits,
    BackupArchiveError,
    FullRestoreIdempotencyConflict,
    create_full_restore_preview,
)
from app.modules.exports.service import (
    ExportIdempotencyConflict,
    create_export_task,
)
from app.modules.exports.tasks import get_export_enqueuer
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.permissions import Permission, PermissionDenied, require_permission


router = APIRouter(prefix="/v1/workspaces/{workspace_id}/exports", tags=["exports"])
restore_router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/restore-previews",
    tags=["exports"],
)
zip_restore_router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/zip-restores",
    tags=["exports"],
)
DatabaseSession = Annotated[Session, Depends(get_session)]
ObjectStorage = Annotated[Storage, Depends(get_storage)]


def get_restore_enqueuer() -> Callable[[UUID], None]:
    from app.modules.exports.restore_tasks import enqueue_restore

    return enqueue_restore


class ExportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["csv", "markdown", "json", "zip"]
    content_id: UUID | None = None


class ExportTaskRead(BaseModel):
    id: UUID
    workspace_id: UUID
    kind: Literal["csv", "markdown", "json", "zip"]
    content_id: UUID | None
    status: Literal["queued", "running", "succeeded", "failed"]
    file_name: str | None
    mime_type: str | None
    download_url: str | None
    download_expires_at: datetime | None
    error_code: str | None
    requested_by: UUID
    created_at: datetime
    completed_at: datetime | None


class ExportTaskPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ExportTaskRead]
    page: int
    page_size: int
    total: int


class KnowledgeIndexRebuildRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Literal["douyin", "xiaohongshu"]
    status: Literal[
        "queued",
        "running",
        "succeeded",
        "failed",
        "configuration_required",
    ]
    error_code: str | None


class FullRestoreRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    workspace_id: UUID
    target_workspace_id: UUID
    mode: Literal["new", "merge"]
    status: Literal[
        "queued",
        "running",
        "succeeded",
        "failed",
        "retrying",
        "cancelled",
    ]
    phase: Literal[
        "uploaded",
        "validating",
        "preview_ready",
        "database",
        "moving_objects",
        "rebuilding_index",
        "completed",
        "failed",
        "compensation_required",
    ]
    preview_id: str
    manifest_fingerprint: str
    preview: dict[str, object]
    error_code: str | None
    knowledge_index_message: str | None
    knowledge_indexes: list[KnowledgeIndexRebuildRead]


class FullRestoreConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_id: str
    manifest_fingerprint: str


def _context(
    session: Session,
    workspace_id: UUID,
    session_token: str | None,
    csrf_token: str | None,
    *,
    mutation: bool,
    permission: Permission = Permission.WRITE_CONTENT,
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
        require_permission(context.role, permission)
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
        requested_by=task.requested_by,
        created_at=task.created_at,
        completed_at=task.completed_at,
    )


def _restore_payload(session: Session, job: RestoreJob) -> FullRestoreRead:
    knowledge_indexes = list(
        session.scalars(
            select(KnowledgeIndexRebuild)
            .where(KnowledgeIndexRebuild.restore_job_id == job.id)
            .order_by(KnowledgeIndexRebuild.platform, KnowledgeIndexRebuild.id)
        )
    )
    return FullRestoreRead(
        id=job.id,
        workspace_id=job.workspace_id,
        target_workspace_id=job.target_workspace_id,
        mode=cast(Literal["new", "merge"], job.mode),
        status=job.status.value,
        phase=job.phase.value,
        preview_id=job.preview_id,
        manifest_fingerprint=job.manifest_fingerprint,
        preview=job.preview_json,
        error_code=job.error_code,
        knowledge_index_message=job.knowledge_index_message,
        knowledge_indexes=[
            KnowledgeIndexRebuildRead(
                platform=index.platform.value,
                status=index.status.value,
                error_code=index.error_code,
            )
            for index in knowledge_indexes
        ],
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


@router.get("", response_model=ExportTaskPage)
def list_exports(
    workspace_id: UUID,
    session: DatabaseSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> ExportTaskPage:
    _context(
        session,
        workspace_id,
        session_token,
        None,
        mutation=False,
        permission=Permission.READ_CONTENT,
    )
    total = session.scalar(
        select(func.count()).select_from(ExportTask).where(
            ExportTask.workspace_id == workspace_id
        )
    ) or 0
    tasks = list(
        session.scalars(
            select(ExportTask)
            .where(ExportTask.workspace_id == workspace_id)
            .order_by(ExportTask.created_at.desc(), ExportTask.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return ExportTaskPage(
        items=[_payload(task) for task in tasks],
        page=page,
        page_size=page_size,
        total=total,
    )


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


@restore_router.post("", response_model=RestorePreview)
async def preview_restore(
    workspace_id: UUID,
    mode: RestoreMode,
    file: Annotated[UploadFile, File()],
    session: DatabaseSession,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> RestorePreview:
    context = _context(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=True,
    )
    if context.role != "admin":
        raise HTTPException(status_code=403, detail="permission denied")
    if file.content_type not in {"application/json", "text/json"}:
        raise HTTPException(status_code=415, detail="JSON backup required")
    if file.filename and not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=422, detail="invalid backup file")
    raw = await file.read(MAX_BACKUP_BYTES + 1)
    try:
        manifest = parse_manifest_json(raw)
        return build_restore_preview(
            session,
            context,
            manifest,
            mode=mode,
            idempotency_key=idempotency_key,
        )
    except (BackupFormatError, ValueError) as error:
        raise HTTPException(
            status_code=422,
            detail="invalid backup manifest",
        ) from error


@zip_restore_router.post(
    "",
    response_model=FullRestoreRead,
    status_code=202,
)
async def create_zip_restore(
    workspace_id: UUID,
    mode: RestoreMode,
    file: Annotated[UploadFile, File()],
    session: DatabaseSession,
    storage: ObjectStorage,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> FullRestoreRead:
    context = _context(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=True,
    )
    if context.role != "admin":
        raise HTTPException(status_code=403, detail="permission denied")
    if file.content_type not in {
        "application/zip",
        "application/x-zip-compressed",
    }:
        raise HTTPException(
            status_code=415,
            detail={"code": "BACKUP_ARCHIVE_UNSAFE"},
        )
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=422,
            detail={"code": "BACKUP_ARCHIVE_UNSAFE"},
        )
    payload = await file.read(ArchiveLimits().max_upload_bytes + 1)
    try:
        job, _ = create_full_restore_preview(
            session,
            context,
            payload,
            storage,
            mode=mode,
            idempotency_key=idempotency_key,
        )
    except BackupArchiveError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": error.code},
        ) from error
    except FullRestoreIdempotencyConflict as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "RESTORE_CONFLICT"},
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "BACKUP_REFERENCE_INVALID"},
        ) from error
    session.commit()
    return _restore_payload(session, job)


@zip_restore_router.get(
    "/{restore_id}",
    response_model=FullRestoreRead,
)
def read_zip_restore(
    workspace_id: UUID,
    restore_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> FullRestoreRead:
    _context(
        session,
        workspace_id,
        session_token,
        None,
        mutation=False,
    )
    job = session.scalar(
        select(RestoreJob).where(
            RestoreJob.id == restore_id,
            RestoreJob.workspace_id == workspace_id,
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="restore not found")
    return _restore_payload(session, job)


@zip_restore_router.post(
    "/{restore_id}/confirm",
    response_model=FullRestoreRead,
    status_code=202,
)
def confirm_zip_restore(
    workspace_id: UUID,
    restore_id: UUID,
    data: FullRestoreConfirm,
    session: DatabaseSession,
    enqueuer: Annotated[
        Callable[[UUID], None],
        Depends(get_restore_enqueuer),
    ],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> FullRestoreRead:
    context = _context(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=True,
    )
    if context.role != "admin":
        raise HTTPException(status_code=403, detail="permission denied")
    job = session.scalar(
        select(RestoreJob).where(
            RestoreJob.id == restore_id,
            RestoreJob.workspace_id == workspace_id,
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="restore not found")
    if (
        data.preview_id != job.preview_id
        or data.manifest_fingerprint != job.manifest_fingerprint
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "RESTORE_PREVIEW_STALE"},
        )
    if (
        job.confirm_idempotency_key is not None
        and job.confirm_idempotency_key != idempotency_key
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "RESTORE_CONFLICT"},
        )
    if not idempotency_key.strip() or len(idempotency_key) > 200:
        raise HTTPException(status_code=422, detail="invalid idempotency key")
    if job.status is not FullRestoreStatus.SUCCEEDED:
        job.confirm_idempotency_key = idempotency_key
        job.status = FullRestoreStatus.QUEUED
        job.phase = FullRestorePhase.PREVIEW_READY
        session.commit()
        try:
            enqueuer(job.id)
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="restore queue unavailable",
            ) from error
    return _restore_payload(session, job)
