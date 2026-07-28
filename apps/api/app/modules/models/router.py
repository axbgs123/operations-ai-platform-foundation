from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_session
from app.modules.models.capabilities import AdapterStatus, Capability
from app.modules.models.catalog import QianwenRegion
from app.modules.models.config_service import (
    ModelConfigRead,
    ModelConfigService,
    ModelConfigurationRequired,
    SecretCipher,
)
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.permissions import PermissionDenied


router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/model-configs",
    tags=["model-configs"],
)
DatabaseSession = Annotated[Session, Depends(get_session)]


class ModelConfigCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=80)
    model_id: str = Field(min_length=1, max_length=160)
    region: QianwenRegion | None = None
    provider_workspace_id: str | None = Field(default=None, min_length=1, max_length=80)
    capabilities: frozenset[Capability] = Field(min_length=1)
    status: AdapterStatus
    api_key: SecretStr


class ModelConfigStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AdapterStatus


def _service(
    session: Session,
    workspace_id: UUID,
    session_token: str | None,
    csrf_token: str | None,
    *,
    mutation: bool,
) -> ModelConfigService:
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
    key = get_settings().model_secret_encryption_key.get_secret_value()
    return ModelConfigService(session, context, cipher=SecretCipher(key))


@router.post("", response_model=ModelConfigRead, status_code=201)
def create_model_config(
    workspace_id: UUID,
    data: ModelConfigCreate,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> ModelConfigRead:
    service = _service(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=True,
    )
    try:
        config = service.save(
            provider=data.provider,
            model_id=data.model_id,
            capabilities=data.capabilities,
            status=data.status,
            api_key=data.api_key.get_secret_value(),
            region=data.region,
            provider_workspace_id=data.provider_workspace_id,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return service.public(config)


@router.get("", response_model=list[ModelConfigRead])
def list_model_configs(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[ModelConfigRead]:
    service = _service(
        session,
        workspace_id,
        session_token,
        None,
        mutation=False,
    )
    try:
        return service.list_public()
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error


@router.get("/selection", response_model=ModelConfigRead)
def select_model_config(
    workspace_id: UUID,
    capability: Capability,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> ModelConfigRead:
    service = _service(
        session,
        workspace_id,
        session_token,
        None,
        mutation=False,
    )
    try:
        return service.public(service.resolve({capability}))
    except ModelConfigurationRequired as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": error.code,
                "message": str(error),
                "action": error.action,
                "required_capabilities": [
                    item.value for item in error.required_capabilities
                ],
            },
        ) from error
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error


@router.patch("/{config_id}", response_model=ModelConfigRead)
def update_model_config_status(
    workspace_id: UUID,
    config_id: UUID,
    data: ModelConfigStatusUpdate,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> ModelConfigRead:
    service = _service(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=True,
    )
    try:
        config = service.set_status(config_id, data.status)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return service.public(config)
