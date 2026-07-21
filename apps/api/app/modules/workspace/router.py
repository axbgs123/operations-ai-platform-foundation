from collections import defaultdict, deque
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_session
from app.core.security import WorkspaceContext
from app.modules.workspace.auth import (
    InviteAuthService,
    InviteRateLimitExceeded,
    InvalidInviteCode,
)
from app.modules.workspace.models import MemberRole
from app.modules.workspace.permissions import PermissionDenied
from app.modules.workspace.schemas import (
    InviteLogin,
    MemberCodeCreate,
    MemberCodeCreated,
    SessionCreated,
    WorkspaceCreate,
    WorkspaceCreated,
    WorkspaceMemberRead,
    WorkspaceMemberUpdate,
)


router = APIRouter(prefix="/v1", tags=["workspace"])
DatabaseSession = Annotated[Session, Depends(get_session)]
invite_attempts: dict[str, deque[datetime]] = defaultdict(deque)


def _authorized_service(
    session: Session,
    workspace_id: UUID,
    session_token: str | None,
    csrf_token: str | None,
) -> tuple[InviteAuthService, WorkspaceContext]:
    if session_token is None or csrf_token is None:
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    service = InviteAuthService(session)
    context = service.authenticate(session_token)
    if context is None:
        raise HTTPException(status_code=401, detail="invalid session")
    if context.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="workspace not found")
    if not service.validate_csrf(session_token, csrf_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return service, context


@router.post("/workspaces", response_model=WorkspaceCreated, status_code=201)
def create_workspace(data: WorkspaceCreate, session: DatabaseSession) -> WorkspaceCreated:
    issued = InviteAuthService(session).create_workspace(data.name)
    session.commit()
    return WorkspaceCreated(
        workspace_id=issued.workspace_id,
        admin_code=issued.admin_code,
    )


@router.post("/sessions/invite", response_model=SessionCreated, status_code=201)
def create_invite_session(
    data: InviteLogin,
    request: Request,
    response: Response,
    session: DatabaseSession,
) -> SessionCreated:
    try:
        authenticated = InviteAuthService(session, attempts=invite_attempts).redeem(
            data.code,
            display_name=data.display_name,
            client_key=request.client.host if request.client else "unknown",
        )
    except InvalidInviteCode as error:
        raise HTTPException(status_code=401, detail="invalid invite code") from error
    except InviteRateLimitExceeded as error:
        raise HTTPException(status_code=429, detail="too many attempts") from error

    session.commit()
    response.set_cookie(
        key="session",
        value=authenticated.session_token,
        max_age=14 * 24 * 60 * 60,
        httponly=True,
        secure=get_settings().app_env != "development",
        samesite="lax",
        path="/",
    )
    return SessionCreated(
        workspace_id=authenticated.context.workspace_id,
        member_id=authenticated.member_id,
        csrf_token=authenticated.csrf_token,
    )


@router.delete("/sessions/current", status_code=204)
def delete_current_session(
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> Response:
    if session_token is None or csrf_token is None:
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    service = InviteAuthService(session)
    if not service.validate_csrf(session_token, csrf_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    service.logout(session_token)
    session.commit()
    response = Response(status_code=204)
    response.delete_cookie("session", path="/")
    return response


@router.post(
    "/workspaces/{workspace_id}/members/codes",
    response_model=MemberCodeCreated,
    status_code=201,
)
def create_member_code(
    workspace_id: UUID,
    data: MemberCodeCreate,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> MemberCodeCreated:
    service, context = _authorized_service(
        session, workspace_id, session_token, csrf_token
    )
    try:
        code = service.issue_member_code(context, MemberRole(data.role))
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    session.commit()
    return MemberCodeCreated(code=code, role=data.role)


@router.patch(
    "/workspaces/{workspace_id}/members/{member_id}",
    response_model=WorkspaceMemberRead,
)
def update_member(
    workspace_id: UUID,
    member_id: UUID,
    data: WorkspaceMemberUpdate,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> WorkspaceMemberRead:
    service, context = _authorized_service(
        session, workspace_id, session_token, csrf_token
    )
    try:
        if data.role is not None:
            member = service.update_member_role(
                context,
                member_id,
                MemberRole(data.role),
            )
        else:
            member = service.revoke_member(context, member_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail="member not found") from error
    session.commit()
    return WorkspaceMemberRead.model_validate(member)
