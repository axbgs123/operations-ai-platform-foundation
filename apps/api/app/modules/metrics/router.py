from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.modules.metrics.models import DataSnapshot, SnapshotSource
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


def _payload(service: SnapshotService, snapshot: DataSnapshot) -> dict:
    completeness = service.completeness(snapshot.content_id)
    return {
        "id": snapshot.id,
        "workspace_id": snapshot.workspace_id,
        "content_id": snapshot.content_id,
        "platform": snapshot.platform.value,
        "content_type": snapshot.content_type.value,
        "collected_at": snapshot.collected_at,
        "age_seconds": snapshot.age_seconds,
        "maturity_bucket": snapshot.maturity_bucket,
        "source": snapshot.source.value,
        "confirmed": snapshot.confirmed,
        "confirmed_at": snapshot.confirmed_at,
        "original_screenshot_asset_id": snapshot.original_screenshot_asset_id,
        "metrics": [
            {
                "key": value.metric_key,
                "raw_value": value.raw_value,
                "normalized_value": value.normalized_value,
                "ocr_confidence": value.ocr_confidence,
                "eligible_for_benchmark": value.eligible_for_benchmark,
            }
            for value in service.values(snapshot.id)
        ],
        "completeness": {
            "observed": list(completeness.observed),
            "missing": list(completeness.missing),
            "ratio": completeness.ratio,
        },
    }


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
    return _payload(service, snapshot)


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
    return [_payload(service, snapshot) for snapshot in snapshots]


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
    return _payload(service, snapshot)


@router.post("/{snapshot_id}/confirm", response_model=SnapshotRead)
def confirm_snapshot(
    content_id: UUID,
    snapshot_id: UUID,
    session: DatabaseSession,
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
    session.commit()
    return _payload(service, snapshot)
