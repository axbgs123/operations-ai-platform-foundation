from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.modules.analysis.service import AnalysisService, account_auto_analysis_enabled
from app.modules.analysis.tasks import get_auto_analysis_enqueuer
from app.modules.metrics.models import SnapshotSource
from app.modules.metrics.schemas import SnapshotCreate, SnapshotRead
from app.modules.metrics.snapshot_service import SnapshotService
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.permissions import PermissionDenied


router = APIRouter(prefix="/v1/contents/{content_id}/snapshots", tags=["metrics"])
DatabaseSession = Annotated[Session, Depends(get_session)]


def _service(
    session: Session,
    session_token: str | None,
    csrf_token: str | None,
    *,
    mutation: bool,
) -> SnapshotService:
    if session_token is None:
        raise HTTPException(status_code=401, detail="invalid session")
    auth = InviteAuthService(session)
    context = auth.authenticate(session_token)
    if context is None:
        raise HTTPException(status_code=401, detail="invalid session")
    if mutation and (
        csrf_token is None or not auth.validate_csrf(session_token, csrf_token)
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return SnapshotService(session, context)


@router.post("", response_model=SnapshotRead, status_code=201)
def create_snapshot(
    content_id: UUID,
    data: SnapshotCreate,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    service = _service(session, session_token, csrf_token, mutation=True)
    try:
        snapshot = service.create(
            content_id,
            collected_at=data.collected_at,
            source=SnapshotSource(data.source),
            metrics=data.metrics,
            original_screenshot_asset_id=data.original_screenshot_asset_id,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return service.read_payload(snapshot)


@router.get("", response_model=list[SnapshotRead])
def list_snapshots(
    content_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[dict]:
    service = _service(session, session_token, None, mutation=False)
    try:
        snapshots = service.list_snapshots(content_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return [service.read_payload(snapshot) for snapshot in snapshots]


@router.get("/{snapshot_id}", response_model=SnapshotRead)
def read_snapshot(
    content_id: UUID,
    snapshot_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> dict:
    service = _service(session, session_token, None, mutation=False)
    try:
        snapshot = service.read(content_id, snapshot_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return service.read_payload(snapshot)


@router.post("/{snapshot_id}/confirm", response_model=SnapshotRead)
def confirm_snapshot(
    content_id: UUID,
    snapshot_id: UUID,
    background_tasks: BackgroundTasks,
    session: DatabaseSession,
    auto_enqueuer: Annotated[
        Callable[[UUID], None], Depends(get_auto_analysis_enqueuer)
    ],
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    service = _service(session, session_token, csrf_token, mutation=True)
    try:
        snapshot = service.confirm(content_id, snapshot_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    auto_enabled = account_auto_analysis_enabled(
        session,
        snapshot.workspace_id,
        snapshot.account_id,
    )
    analysis_run = None
    should_enqueue = False
    if auto_enabled:
        assert session_token is not None
        context = InviteAuthService(session).authenticate(session_token)
        assert context is not None
        analysis_run, should_enqueue, _ = AnalysisService(
            session, context
        ).request(
            content_id,
            trigger_kind="auto",
        )
    session.commit()
    if analysis_run is not None and should_enqueue:
        background_tasks.add_task(auto_enqueuer, analysis_run.id)
    return service.read_payload(snapshot)
