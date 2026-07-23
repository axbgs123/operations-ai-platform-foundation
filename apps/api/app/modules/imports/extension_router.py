from collections import defaultdict, deque
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.modules.imports.extension_auth import (
    AuthenticatedExtension,
    ExtensionTokenService,
)
from app.modules.imports.models import ExtensionToken, ExtensionTokenScope
from app.modules.workspace.auth import InvalidInviteCode, InviteRateLimitExceeded


router = APIRouter(prefix="/v1/extension", tags=["extension-auth"])
DatabaseSession = Annotated[Session, Depends(get_session)]
binding_attempts: dict[str, deque[datetime]] = defaultdict(deque)


class ExtensionBindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invite_code: str = Field(min_length=20, max_length=500)
    client_id: str = Field(min_length=3, max_length=120)


class ExtensionBindResponse(BaseModel):
    access_token: str
    token_type: str
    workspace_id: UUID
    member_id: UUID
    client_id: str
    scopes: list[str]
    issued_at: datetime
    expires_at: datetime


class ExtensionBindingRead(BaseModel):
    workspace_id: UUID
    member_id: UUID
    client_id: str
    scopes: list[str]
    expires_at: datetime


def _bearer(
    session: Session,
    authorization: str | None,
    *,
    required_scope: ExtensionTokenScope | None = None,
    workspace_id: UUID | None = None,
) -> AuthenticatedExtension:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="invalid extension token")
    token = authorization.removeprefix("Bearer ").strip()
    authenticated = ExtensionTokenService(session).authenticate(token)
    if authenticated is None:
        raise HTTPException(status_code=401, detail="invalid extension token")
    if workspace_id is not None and authenticated.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="extension resource not found")
    if (
        required_scope is not None
        and required_scope.value not in authenticated.scopes
    ):
        raise HTTPException(status_code=403, detail="extension scope denied")
    return authenticated


@router.post("/bind", response_model=ExtensionBindResponse, status_code=201)
def bind_extension(
    data: ExtensionBindRequest,
    request: Request,
    session: DatabaseSession,
    extension_client: Annotated[
        str | None, Header(alias="X-Extension-Client")
    ] = None,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key")
    ] = None,
) -> ExtensionBindResponse:
    if extension_client is None or extension_client != data.client_id:
        raise HTTPException(status_code=422, detail="invalid extension client")
    key = idempotency_key or f"{data.client_id}:{data.invite_code}"
    fingerprint = ExtensionTokenService._digest(key)
    if session.scalar(
        select(ExtensionToken.id).where(
            ExtensionToken.exchange_fingerprint == fingerprint
        )
    ):
        raise HTTPException(status_code=409, detail="binding already exchanged")
    service = ExtensionTokenService(session, attempts=binding_attempts)
    try:
        issued = service.bind(
            data.invite_code,
            client_id=data.client_id,
            display_name="扩展成员",
            client_key=request.client.host if request.client else "unknown",
        )
        record = session.get(ExtensionToken, issued.token_id)
        assert record is not None
        record.exchange_fingerprint = fingerprint
        session.commit()
    except InvalidInviteCode as error:
        raise HTTPException(status_code=401, detail="invalid invite code") from error
    except InviteRateLimitExceeded as error:
        raise HTTPException(status_code=429, detail="too many attempts") from error
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="binding already exchanged") from error
    return ExtensionBindResponse(
        access_token=issued.access_token,
        token_type="Bearer",
        workspace_id=issued.workspace_id,
        member_id=issued.member_id,
        client_id=issued.client_id,
        scopes=list(issued.scopes),
        issued_at=issued.issued_at,
        expires_at=issued.expires_at,
    )


@router.get("/binding", response_model=ExtensionBindingRead)
def read_extension_binding(
    session: DatabaseSession,
    authorization: Annotated[
        str | None, Header(alias="Authorization")
    ] = None,
) -> ExtensionBindingRead:
    authenticated = _bearer(
        session,
        authorization,
        required_scope=ExtensionTokenScope.CAPTURE_READ,
    )
    return ExtensionBindingRead(
        workspace_id=authenticated.workspace_id,
        member_id=authenticated.member_id,
        client_id=authenticated.client_id,
        scopes=list(authenticated.scopes),
        expires_at=authenticated.expires_at,
    )


@router.get(
    "/workspaces/{workspace_id}/binding",
    response_model=ExtensionBindingRead,
)
def read_scoped_extension_binding(
    workspace_id: UUID,
    session: DatabaseSession,
    authorization: Annotated[
        str | None, Header(alias="Authorization")
    ] = None,
) -> ExtensionBindingRead:
    authenticated = _bearer(
        session,
        authorization,
        required_scope=ExtensionTokenScope.CAPTURE_READ,
        workspace_id=workspace_id,
    )
    return ExtensionBindingRead(
        workspace_id=authenticated.workspace_id,
        member_id=authenticated.member_id,
        client_id=authenticated.client_id,
        scopes=list(authenticated.scopes),
        expires_at=authenticated.expires_at,
    )


@router.delete("/binding", status_code=status.HTTP_204_NO_CONTENT)
def revoke_extension_binding(
    session: DatabaseSession,
    authorization: Annotated[
        str | None, Header(alias="Authorization")
    ] = None,
) -> None:
    authenticated = _bearer(session, authorization)
    ExtensionTokenService(session).revoke(authenticated.token_id)
    session.commit()
