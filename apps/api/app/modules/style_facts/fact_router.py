from datetime import datetime
from collections.abc import Callable
from typing import Annotated, Literal, Self
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
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.modules.style_facts.fact_models import (
    FactItem,
    FactSource,
    FactSourceKind,
    FactSourceLevel,
    FactSourceStatus,
)
from app.modules.style_facts.fact_tasks import get_fact_source_enqueuer
from app.modules.style_facts.source_ingestion import (
    MAX_DOCUMENT_SIZE,
    FactSourceService,
    FactUploadTooLarge,
)
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.permissions import PermissionDenied


router = APIRouter(tags=["fact-sources"])
DatabaseSession = Annotated[Session, Depends(get_session)]


class FactSourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["text", "link", "web"]
    level: FactSourceLevel
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(default="", max_length=500_000)
    url: str | None = Field(default=None, max_length=2048)
    published_at: datetime | None = None

    @model_validator(mode="after")
    def require_aware_published_at(self) -> Self:
        if self.published_at is not None and self.published_at.tzinfo is None:
            raise ValueError("published_at timezone is required")
        return self


class FactItemRead(BaseModel):
    id: UUID
    source_id: UUID
    field_name: str
    value: str
    source_location: str
    confidence: float
    status: Literal["candidate", "confirmed"]
    conflict_status: Literal["clear", "unresolved", "resolved"]
    confirmed_by: UUID | None
    confirmed_at: datetime | None
    override_record: dict[str, object] | None


class FactSourceRead(BaseModel):
    id: UUID
    workspace_id: UUID
    kind: Literal["document", "image", "link", "text", "web"]
    level: FactSourceLevel
    title: str
    status: Literal["parsed", "awaiting_fetch", "awaiting_model", "failed"]
    source_url: str | None
    resolved_ips: list[str]
    file_name: str | None
    mime_type: str | None
    size: int | None
    content_sha256: str | None
    published_at: datetime | None
    accessed_at: datetime | None
    untrusted_data: bool
    status_detail: dict[str, object]
    items: list[FactItemRead]
    created_at: datetime


class FactContextRead(BaseModel):
    unconstrained_facts: bool
    has_sources: bool
    requires_confirmation: bool
    confirmed_items: list[FactItemRead]


def _service(
    session: Session,
    workspace_id: UUID,
    session_token: str | None,
    csrf_token: str | None,
    *,
    mutation: bool,
) -> FactSourceService:
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
    return FactSourceService(session, context)


def _item_payload(item: FactItem) -> dict[str, object]:
    return {
        "id": item.id,
        "source_id": item.source_id,
        "field_name": item.field_name,
        "value": item.value,
        "source_location": item.source_location,
        "confidence": item.confidence,
        "status": item.status.value,
        "conflict_status": item.conflict_status.value,
        "confirmed_by": item.confirmed_by,
        "confirmed_at": item.confirmed_at,
        "override_record": item.override_record,
    }


def _source_payload(
    service: FactSourceService,
    source: FactSource,
) -> dict[str, object]:
    return {
        "id": source.id,
        "workspace_id": source.workspace_id,
        "kind": source.kind.value,
        "level": source.level.value,
        "title": source.title,
        "status": source.status.value,
        "source_url": source.source_url,
        "resolved_ips": source.resolved_ips,
        "file_name": source.file_name,
        "mime_type": source.mime_type,
        "size": source.size,
        "content_sha256": source.content_sha256,
        "published_at": source.published_at,
        "accessed_at": source.accessed_at,
        "untrusted_data": source.untrusted_data,
        "status_detail": source.status_detail,
        "items": [_item_payload(item) for item in service.items(source.id)],
        "created_at": source.created_at,
    }


@router.post(
    "/v1/workspaces/{workspace_id}/fact-sources",
    response_model=FactSourceRead,
    status_code=201,
)
def create_fact_source(
    workspace_id: UUID,
    data: FactSourceCreate,
    session: DatabaseSession,
    background_tasks: BackgroundTasks,
    enqueuer: Annotated[
        Callable[[str, str, str], None], Depends(get_fact_source_enqueuer)
    ],
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict[str, object]:
    service = _service(session, workspace_id, session_token, csrf_token, mutation=True)
    try:
        source = service.create_source(
            kind=FactSourceKind(data.kind),
            level=data.level,
            title=data.title,
            content=data.content,
            url=data.url,
            published_at=data.published_at,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    if source.status is FactSourceStatus.AWAITING_FETCH:
        background_tasks.add_task(
            enqueuer,
            str(source.workspace_id),
            str(source.created_by),
            str(source.id),
        )
    return _source_payload(service, source)


@router.post(
    "/v1/workspaces/{workspace_id}/fact-sources/upload",
    response_model=FactSourceRead,
    status_code=201,
)
async def upload_fact_source(
    workspace_id: UUID,
    session: DatabaseSession,
    background_tasks: BackgroundTasks,
    enqueuer: Annotated[
        Callable[[str, str, str], None], Depends(get_fact_source_enqueuer)
    ],
    kind: Annotated[FactSourceKind, Form()],
    level: Annotated[FactSourceLevel, Form()],
    title: Annotated[str, Form(min_length=1, max_length=300)],
    file: Annotated[UploadFile, File()],
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict[str, object]:
    service = _service(session, workspace_id, session_token, csrf_token, mutation=True)
    content = await file.read(MAX_DOCUMENT_SIZE + 1)
    try:
        source = service.upload_source(
            kind=kind,
            level=level,
            title=title,
            file_name=file.filename or "source",
            mime_type=file.content_type or "application/octet-stream",
            content=content,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except FactUploadTooLarge as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    if source.status is FactSourceStatus.AWAITING_MODEL:
        background_tasks.add_task(
            enqueuer,
            str(source.workspace_id),
            str(source.created_by),
            str(source.id),
        )
    return _source_payload(service, source)


@router.get(
    "/v1/workspaces/{workspace_id}/fact-sources",
    response_model=list[FactSourceRead],
)
def list_fact_sources(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[dict[str, object]]:
    service = _service(session, workspace_id, session_token, None, mutation=False)
    try:
        return [_source_payload(service, source) for source in service.sources()]
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error


@router.get(
    "/v1/workspaces/{workspace_id}/fact-sources/{source_id}",
    response_model=FactSourceRead,
)
def read_fact_source(
    workspace_id: UUID,
    source_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> dict[str, object]:
    service = _service(session, workspace_id, session_token, None, mutation=False)
    try:
        return _source_payload(service, service.source(source_id))
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post(
    "/v1/workspaces/{workspace_id}/fact-items/{item_id}/confirm",
    response_model=FactItemRead,
)
def confirm_fact_item(
    workspace_id: UUID,
    item_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict[str, object]:
    service = _service(session, workspace_id, session_token, csrf_token, mutation=True)
    try:
        item = service.confirm_item(item_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    session.commit()
    return _item_payload(item)


@router.get(
    "/v1/workspaces/{workspace_id}/fact-context",
    response_model=FactContextRead,
)
def read_fact_context(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> dict[str, object]:
    service = _service(session, workspace_id, session_token, None, mutation=False)
    try:
        context = service.context()
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    return {
        **context,
        "confirmed_items": [
            _item_payload(item) for item in context["confirmed_items"]
        ],
    }
