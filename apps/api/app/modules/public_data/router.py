from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.security import WorkspaceContext
from app.modules.public_data.contracts import PublicProviderError
from app.modules.public_data.schemas import (
    CollectionJobRead,
    ContentBindingInput,
    ContentBindingRead,
    ProviderConfigInput,
    ProviderConfigRead,
    ProviderConnectionRead,
)
from app.modules.public_data.service import PublicDataService, run_collection_job
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.permissions import PermissionDenied


router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/public-data", tags=["public-data"]
)
DatabaseSession = Annotated[Session, Depends(get_session)]


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
        csrf_token is None or not auth.validate_csrf(session_token, csrf_token)
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return context


def _config_payload(config) -> dict[str, object]:
    return {
        "id": config.id,
        "provider": "tikhub",
        "endpoint_region": config.endpoint_region,
        "status": config.status.value,
        "daily_request_limit": config.daily_request_limit,
        "daily_requests_used": (
            config.daily_requests_used
            if config.daily_usage_date == datetime.now(UTC).date()
            else 0
        ),
        "configuration_revision": config.configuration_revision,
        "last_tested_at": config.last_tested_at,
        "safe_error_code": config.safe_error_code,
        "has_api_key": True,
    }


@router.put("/provider", response_model=ProviderConfigRead)
def save_provider(
    workspace_id: UUID,
    data: ProviderConfigInput,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict[str, object]:
    service = PublicDataService(
        session,
        _context(session, workspace_id, session_token, csrf_token, mutation=True),
    )
    try:
        config = service.save_config(
            api_key=data.api_key.get_secret_value(),
            endpoint_region=data.endpoint_region,
            daily_request_limit=data.daily_request_limit,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    session.commit()
    return _config_payload(config)


@router.get("/provider", response_model=ProviderConfigRead | None)
def read_provider(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> dict[str, object] | None:
    service = PublicDataService(
        session,
        _context(session, workspace_id, session_token, None, mutation=False),
    )
    try:
        config = service.read_config()
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    return _config_payload(config) if config is not None else None


@router.post("/provider/test", response_model=ProviderConnectionRead)
def test_provider(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> ProviderConnectionRead:
    service = PublicDataService(
        session,
        _context(session, workspace_id, session_token, csrf_token, mutation=True),
    )
    try:
        config, connected = service.test_config()
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PublicProviderError as error:
        raise HTTPException(status_code=429, detail=error.code) from error
    session.commit()
    return ProviderConnectionRead(
        connected=connected,
        status="verified" if connected else "failed",
        checked_at=config.last_tested_at or datetime.now(UTC),
        safe_error_code=config.safe_error_code,
    )


@router.put("/contents/{content_id}/binding", response_model=ContentBindingRead)
def bind_content(
    workspace_id: UUID,
    content_id: UUID,
    data: ContentBindingInput,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict[str, object]:
    service = PublicDataService(
        session,
        _context(session, workspace_id, session_token, csrf_token, mutation=True),
    )
    try:
        binding = service.bind_content(
            content_id,
            public_url=str(data.public_url),
            published_at=data.published_at,
            platform_content_id=data.platform_content_id,
        )
        payload = service.binding_payload(binding)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PublicProviderError as error:
        status_code = (
            429 if error.code == "PUBLIC_PROVIDER_DAILY_LIMIT_REACHED" else 422
        )
        raise HTTPException(status_code=status_code, detail=error.code) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return payload


@router.get("/contents/{content_id}/binding", response_model=ContentBindingRead)
def read_binding(
    workspace_id: UUID,
    content_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> dict[str, object]:
    service = PublicDataService(
        session,
        _context(session, workspace_id, session_token, None, mutation=False),
    )
    try:
        return service.binding_payload(service.read_binding(content_id))
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post(
    "/contents/{content_id}/collect-now",
    response_model=CollectionJobRead,
    status_code=202,
)
def collect_now(
    workspace_id: UUID,
    content_id: UUID,
    background_tasks: BackgroundTasks,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict[str, object]:
    service = PublicDataService(
        session,
        _context(session, workspace_id, session_token, csrf_token, mutation=True),
    )
    try:
        job = service.collect_now(content_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    payload = {
        "id": job.id,
        "target_window": job.target_window,
        "due_at": job.due_at,
        "next_attempt_at": job.next_attempt_at,
        "status": job.status.value,
        "attempt_count": job.attempt_count,
        "snapshot_id": job.snapshot_id,
        "safe_error_code": job.safe_error_code,
    }
    session.commit()
    background_tasks.add_task(run_collection_job, job.id)
    return payload
