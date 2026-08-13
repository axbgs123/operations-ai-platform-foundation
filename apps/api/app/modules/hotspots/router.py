from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    Header,
    HTTPException,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_session
from app.core.security import WorkspaceContext
from app.core.storage import Storage, get_storage
from app.modules.content.account_models import Platform
from app.modules.hotspots.models import (
    CaptureCompleteness,
    HotspotCaptureTask,
    HotspotEntry,
    HotspotSnapshot,
)
from app.modules.hotspots.service import (
    HotspotConflict,
    confirm_capture,
    create_capture,
)
from app.modules.hotspots.tasks import get_hotspot_enqueuer
from app.modules.imports.vision_binding import resolve_vision_binding
from app.modules.metrics.models import ContentType
from app.modules.models.config_service import SecretCipher
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.permissions import (
    Permission,
    PermissionDenied,
    require_permission,
)


router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/hotspots",
    tags=["hotspots"],
)
DatabaseSession = Annotated[Session, Depends(get_session)]
ObjectStorage = Annotated[Storage, Depends(get_storage)]


class HotspotCaptureCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_platform: Platform
    source_url: str = Field(min_length=1, max_length=2_000)
    page_title: str = Field(min_length=1, max_length=300)
    collected_at: datetime
    completeness: CaptureCompleteness
    screenshot_data_url: str = Field(min_length=32, max_length=15_000_000)


class HotspotEntryCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: int = Field(ge=1, le=50)
    topic: str = Field(min_length=1, max_length=300)
    rank: int | None = Field(default=None, ge=1, le=999)
    heat: str | None = Field(default=None, max_length=80)
    ocr_text_index: int | None = Field(default=None, ge=0)


class HotspotCaptureRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    workspace_id: UUID
    target_platform: Platform
    source_url: str
    source_host: str
    page_title: str
    collected_at: datetime
    completeness: CaptureCompleteness
    status: str
    candidates: list[HotspotEntryCandidate]
    expires_at: datetime
    provider_mode: str
    model_id: str
    contract_version: str
    error_code: str | None
    confirmed_snapshot_id: UUID | None


class HotspotEntryConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=300)
    rank: int | None = Field(default=None, ge=1, le=999)
    heat: str | None = Field(default=None, max_length=80)
    selected: bool = True


class HotspotConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[HotspotEntryConfirm] = Field(min_length=1, max_length=50)


class HotspotEntryRead(HotspotEntryConfirm):
    id: UUID
    position: int


class HotspotSnapshotRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    workspace_id: UUID
    capture_task_id: UUID
    target_platform: Platform
    source_url: str
    source_host: str
    page_title: str
    collected_at: datetime
    confirmed_at: datetime
    completeness: CaptureCompleteness
    ocr_model_id: str
    ocr_contract_version: str
    entries: list[HotspotEntryRead]


def _context(
    session: Session,
    workspace_id: UUID,
    session_token: str | None,
    csrf_token: str | None = None,
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
        csrf_token is None or not auth.validate_csrf(session_token, csrf_token)
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return context


def _require(context: WorkspaceContext, permission: Permission) -> None:
    try:
        require_permission(context.role, permission)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error


def _capture_read(task: HotspotCaptureTask) -> HotspotCaptureRead:
    return HotspotCaptureRead(
        id=task.id,
        workspace_id=task.workspace_id,
        target_platform=task.target_platform,
        source_url=task.source_url,
        source_host=task.source_host,
        page_title=task.page_title,
        collected_at=task.collected_at,
        completeness=task.completeness,
        status=task.status.value,
        candidates=[HotspotEntryCandidate.model_validate(item) for item in task.candidate_entries],
        expires_at=task.expires_at,
        provider_mode="mock" if task.provider == "mock" else "qianwen",
        model_id=task.model_id,
        contract_version=task.contract_version,
        error_code=task.error_code,
        confirmed_snapshot_id=task.confirmed_snapshot_id,
    )


def _snapshot_read(session: Session, snapshot: HotspotSnapshot) -> HotspotSnapshotRead:
    entries = session.scalars(
        select(HotspotEntry)
        .where(HotspotEntry.snapshot_id == snapshot.id)
        .order_by(HotspotEntry.position)
    ).all()
    return HotspotSnapshotRead(
        id=snapshot.id,
        workspace_id=snapshot.workspace_id,
        capture_task_id=snapshot.capture_task_id,
        target_platform=snapshot.target_platform,
        source_url=snapshot.source_url,
        source_host=snapshot.source_host,
        page_title=snapshot.page_title,
        collected_at=snapshot.collected_at,
        confirmed_at=snapshot.confirmed_at,
        completeness=snapshot.completeness,
        ocr_model_id=snapshot.ocr_model_id,
        ocr_contract_version=snapshot.ocr_contract_version,
        entries=[
            HotspotEntryRead(
                id=item.id,
                position=item.position,
                topic=item.topic,
                rank=item.rank,
                heat=item.heat,
                selected=item.selected,
            )
            for item in entries
        ],
    )


@router.post("/captures", response_model=HotspotCaptureRead, status_code=202)
def create_hotspot_capture(
    workspace_id: UUID,
    data: HotspotCaptureCreate,
    background_tasks: BackgroundTasks,
    session: DatabaseSession,
    storage: ObjectStorage,
    enqueuer=Depends(get_hotspot_enqueuer),
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> HotspotCaptureRead:
    context = _context(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=True,
    )
    _require(context, Permission.WRITE_CONTENT)
    if context.member_id is None:
        raise HTTPException(status_code=403, detail="member identity required")
    if not idempotency_key or len(idempotency_key) > 160:
        raise HTTPException(status_code=400, detail="Idempotency-Key required")
    settings = get_settings()
    try:
        binding = resolve_vision_binding(
            session,
            context,
            platform=data.target_platform,
            content_type=ContentType.VIDEO,
            cipher=SecretCipher(
                settings.model_secret_encryption_key.get_secret_value()
            ),
            mock_mode=settings.app_mock_mode,
        )
        task = create_capture(
            session,
            workspace_id=workspace_id,
            member_id=context.member_id,
            target_platform=data.target_platform,
            source_url=data.source_url,
            page_title=data.page_title,
            collected_at=data.collected_at,
            completeness=data.completeness,
            idempotency_key=idempotency_key,
            screenshot_data_url=data.screenshot_data_url,
            binding=binding,
            storage=None if binding.provider == "mock" else storage,
        )
    except LookupError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "MODEL_CONFIGURATION_REQUIRED",
                "message": "请联系管理员配置图片文字识别模型",
            },
        ) from error
    except HotspotConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    if binding.provider != "mock":
        background_tasks.add_task(enqueuer, task.id)
    return _capture_read(task)


@router.get("/captures/{capture_id}", response_model=HotspotCaptureRead)
def read_hotspot_capture(
    workspace_id: UUID,
    capture_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> HotspotCaptureRead:
    context = _context(session, workspace_id, session_token, mutation=False)
    _require(context, Permission.READ_CONTENT)
    task = session.scalar(
        select(HotspotCaptureTask).where(
            HotspotCaptureTask.id == capture_id,
            HotspotCaptureTask.workspace_id == workspace_id,
        )
    )
    if task is None:
        raise HTTPException(status_code=404, detail="hotspot capture not found")
    return _capture_read(task)


@router.post(
    "/captures/{capture_id}/confirm",
    response_model=HotspotSnapshotRead,
)
def confirm_hotspot_capture(
    workspace_id: UUID,
    capture_id: UUID,
    data: HotspotConfirmation,
    session: DatabaseSession,
    storage: ObjectStorage,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> HotspotSnapshotRead:
    context = _context(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=True,
    )
    _require(context, Permission.WRITE_CONTENT)
    if context.member_id is None:
        raise HTTPException(status_code=403, detail="member identity required")
    task = session.scalar(
        select(HotspotCaptureTask).where(
            HotspotCaptureTask.id == capture_id,
            HotspotCaptureTask.workspace_id == workspace_id,
        )
    )
    if task is None:
        raise HTTPException(status_code=404, detail="hotspot capture not found")
    try:
        snapshot = confirm_capture(
            session,
            task=task,
            confirmed_by=context.member_id,
            entries=[item.model_dump(mode="json") for item in data.entries],
            storage=None if task.provider == "mock" else storage,
        )
    except HotspotConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return _snapshot_read(session, snapshot)


@router.get("/snapshots", response_model=list[HotspotSnapshotRead])
def list_hotspot_snapshots(
    workspace_id: UUID,
    session: DatabaseSession,
    target_platform: Platform | None = None,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[HotspotSnapshotRead]:
    context = _context(session, workspace_id, session_token, mutation=False)
    _require(context, Permission.READ_CONTENT)
    query = select(HotspotSnapshot).where(
        HotspotSnapshot.workspace_id == workspace_id
    )
    if target_platform is not None:
        query = query.where(HotspotSnapshot.target_platform == target_platform)
    snapshots = session.scalars(
        query.order_by(desc(HotspotSnapshot.confirmed_at), desc(HotspotSnapshot.id)).limit(100)
    ).all()
    return [_snapshot_read(session, snapshot) for snapshot in snapshots]
