from collections.abc import Callable
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
)
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.modules.content.account_models import Platform
from app.modules.imports.models import ImportBatch, ImportRowStatus
from app.modules.imports.schemas import (
    HeaderMappingUpdate,
    ImportBatchRead,
    ImportConfirmRequest,
    ImportConfirmationRead,
    ImportRowUpdate,
    ManualPreviewRequest,
)
from app.modules.imports.screenshot import get_screenshot_enqueuer
from app.modules.imports.service import ImportService
from app.modules.metrics.models import ContentType
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.permissions import PermissionDenied


router = APIRouter(tags=["imports"])
DatabaseSession = Annotated[Session, Depends(get_session)]
MAX_IMPORT_SIZE = 10 * 1024 * 1024


def _service(
    session: Session,
    session_token: str | None,
    csrf_token: str | None,
    *,
    workspace_id: UUID | None = None,
    require_csrf: bool = True,
) -> ImportService:
    if session_token is None:
        raise HTTPException(status_code=401, detail="invalid session")
    auth = InviteAuthService(session)
    context = auth.authenticate(session_token)
    if context is None:
        raise HTTPException(status_code=401, detail="invalid session")
    if workspace_id is not None and context.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="workspace not found")
    if require_csrf and (
        csrf_token is None or not auth.validate_csrf(session_token, csrf_token)
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return ImportService(session, context)


def _payload(service: ImportService, batch: ImportBatch) -> dict[str, object]:
    rows = service.rows(batch.id)
    summary = {status.value: 0 for status in ImportRowStatus}
    for row in rows:
        summary[row.status.value] += 1
    return {
        "id": batch.id,
        "workspace_id": batch.workspace_id,
        "account_id": batch.account_id,
        "platform": batch.platform.value,
        "content_type": batch.content_type.value,
        "source_kind": batch.source_kind.value,
        "status": batch.status.value,
        "recognition_status": (
            batch.recognition_status.value if batch.recognition_status else None
        ),
        "recognition_error": batch.recognition_error,
        "provider_mode": (
            "mock"
            if batch.recognition_provider == "mock"
            else "qianwen"
        ),
        "region": batch.recognition_region,
        "file_name": batch.file_name,
        "header_mappings": batch.header_mappings,
        "rows": [
            {
                "id": row.id,
                "row_number": row.row_number,
                "status": row.status.value,
                "selected": row.selected,
                "raw_data": row.raw_data,
                "normalized_data": row.normalized_data,
                "errors": row.errors,
                "matched_content_id": row.matched_content_id,
                "dedupe_reason": row.dedupe_reason,
            }
            for row in rows
        ],
        "summary": summary,
    }


@router.get("/v1/imports/{batch_id}", response_model=ImportBatchRead)
def read_import_batch(
    batch_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> dict[str, object]:
    service = _service(
        session,
        session_token,
        None,
        require_csrf=False,
    )
    try:
        return _payload(service, service.read_batch(batch_id))
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post(
    "/v1/workspaces/{workspace_id}/imports/screenshot/recognitions",
    response_model=ImportBatchRead,
    status_code=202,
)
async def stage_screenshot_recognition(
    workspace_id: UUID,
    session: DatabaseSession,
    background_tasks: BackgroundTasks,
    enqueuer: Annotated[
        Callable[[UUID], None], Depends(get_screenshot_enqueuer)
    ],
    account_id: Annotated[UUID, Form()],
    platform: Annotated[Platform, Form()],
    content_type: Annotated[ContentType, Form()],
    title: Annotated[str, Form(min_length=1, max_length=300)],
    body: Annotated[str, Form(max_length=100_000)],
    published_at: Annotated[datetime, Form()],
    collected_at: Annotated[datetime, Form()],
    retention_policy: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict[str, object]:
    service = _service(
        session, session_token, csrf_token, workspace_id=workspace_id
    )
    image = await file.read(MAX_IMPORT_SIZE + 1)
    try:
        batch = service.preview_screenshot(
            account_id=account_id,
            platform=platform,
            content_type=content_type,
            file_name=file.filename or "screenshot.png",
            mime_type=file.content_type or "application/octet-stream",
            image=image,
            title=title,
            body=body,
            published_at=published_at,
            collected_at=collected_at,
            retention_policy=retention_policy,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    background_tasks.add_task(enqueuer, batch.id)
    return _payload(service, batch)


@router.post(
    "/v1/workspaces/{workspace_id}/imports/tabular/preview",
    response_model=ImportBatchRead,
    status_code=201,
)
async def preview_tabular_import(
    workspace_id: UUID,
    session: DatabaseSession,
    account_id: Annotated[UUID, Form()],
    platform: Annotated[Platform, Form()],
    content_type: Annotated[ContentType, Form()],
    file: Annotated[UploadFile, File()],
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict[str, object]:
    service = _service(
        session, session_token, csrf_token, workspace_id=workspace_id
    )
    data = await file.read(MAX_IMPORT_SIZE + 1)
    if len(data) > MAX_IMPORT_SIZE:
        raise HTTPException(status_code=413, detail="import file exceeds 10 MiB")
    try:
        batch = service.preview_file(
            account_id=account_id,
            platform=platform,
            content_type=content_type,
            file_name=file.filename or "import.csv",
            data=data,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return _payload(service, batch)


@router.post(
    "/v1/workspaces/{workspace_id}/imports/manual/preview",
    response_model=ImportBatchRead,
    status_code=201,
)
def preview_manual_import(
    workspace_id: UUID,
    data: ManualPreviewRequest,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict[str, object]:
    service = _service(
        session, session_token, csrf_token, workspace_id=workspace_id
    )
    try:
        batch = service.preview_manual(
            account_id=data.account_id,
            platform=Platform(data.platform),
            content_type=ContentType(data.content_type),
            rows=data.rows,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    session.commit()
    return _payload(service, batch)


@router.patch("/v1/imports/{batch_id}/mapping", response_model=ImportBatchRead)
def update_import_mapping(
    batch_id: UUID,
    data: HeaderMappingUpdate,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict[str, object]:
    service = _service(session, session_token, csrf_token)
    try:
        batch = service.update_mapping(batch_id, data.mapping)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return _payload(service, batch)


@router.patch(
    "/v1/imports/{batch_id}/rows/{row_id}", response_model=ImportBatchRead
)
def update_import_row(
    batch_id: UUID,
    row_id: UUID,
    data: ImportRowUpdate,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict[str, object]:
    service = _service(session, session_token, csrf_token)
    try:
        batch = service.update_row(
            batch_id, row_id, changes=data.changes, selected=data.selected
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return _payload(service, batch)


@router.post(
    "/v1/imports/{batch_id}/confirm", response_model=ImportConfirmationRead
)
def confirm_import(
    batch_id: UUID,
    data: ImportConfirmRequest,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict[str, object]:
    service = _service(session, session_token, csrf_token)
    try:
        result = service.confirm(batch_id, data.selected_row_ids)
        session.commit()
        return result
    except PermissionDenied as error:
        session.rollback()
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
