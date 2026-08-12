from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_session
from app.core.security import WorkspaceContext
from app.modules.workspace.auth import (
    AuthenticatedSession,
    InviteAuthService,
    InviteRateLimitExceeded,
    InvalidInviteCode,
)
from app.modules.workspace.models import MemberRole
from app.modules.workspace.permissions import (
    Permission,
    PermissionDenied,
    require_permission,
)
from app.modules.workspace.repository import (
    WorkspaceAccessCodeRepository,
    WorkspaceMemberRepository,
)
from app.modules.workspace.schemas import (
    InviteLogin,
    MemberCodeCreate,
    MemberCodeCreated,
    SessionCreated,
    WorkspaceCreate,
    WorkspaceCreated,
    WorkspaceMemberRead,
    WorkspaceMemberManagementRead,
    WorkspaceMemberUpdate,
    WorkspaceOwnerOnboard,
)


router = APIRouter(prefix="/v1", tags=["workspace"])
DatabaseSession = Annotated[Session, Depends(get_session)]
invite_attempts: dict[str, deque[datetime]] = defaultdict(deque)


def _render_session(
    response: Response,
    authenticated: AuthenticatedSession,
) -> SessionCreated:
    remaining_seconds = max(
        0,
        int((authenticated.expires_at - datetime.now(UTC)).total_seconds()),
    )
    response.set_cookie(
        key="session",
        value=authenticated.session_token,
        max_age=remaining_seconds,
        expires=authenticated.expires_at,
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


def _member_management_context(
    session: Session,
    workspace_id: UUID,
    session_token: str | None,
) -> WorkspaceContext:
    if session_token is None:
        raise HTTPException(status_code=401, detail="invalid session")
    service = InviteAuthService(session)
    context = service.authenticate(session_token)
    if context is None:
        raise HTTPException(status_code=401, detail="invalid session")
    if context.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="workspace not found")
    try:
        require_permission(context.role, Permission.MANAGE_MEMBERS)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    return context


@router.post("/workspaces", response_model=WorkspaceCreated, status_code=201)
def create_workspace(data: WorkspaceCreate, session: DatabaseSession) -> WorkspaceCreated:
    issued = InviteAuthService(session).create_workspace(data.name)
    session.commit()
    return WorkspaceCreated(
        workspace_id=issued.workspace_id,
        admin_code=issued.admin_code,
    )


@router.post(
    "/workspaces/onboard",
    response_model=SessionCreated,
    status_code=201,
)
def onboard_workspace_owner(
    data: WorkspaceOwnerOnboard,
    response: Response,
    session: DatabaseSession,
) -> SessionCreated:
    authenticated = InviteAuthService(session).create_owner_session(
        workspace_name=data.workspace_name,
        display_name=data.display_name,
    )
    session.commit()
    return _render_session(response, authenticated)


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
    return _render_session(response, authenticated)


@router.post(
    "/sessions/current/resume",
    response_model=SessionCreated,
    status_code=201,
    responses={204: {"description": "No active browser session"}},
)
def resume_current_session(
    request: Request,
    response: Response,
    session: DatabaseSession,
    resume_marker: Annotated[
        str,
        Header(alias="X-Workspace-Resume"),
    ],
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> SessionCreated | Response:
    if (
        request.headers.get("origin") != get_settings().web_origin
        or resume_marker != "resume"
    ):
        raise HTTPException(status_code=403, detail="resume validation failed")
    if session_token is None:
        return Response(status_code=204)
    authenticated = InviteAuthService(session).resume(session_token)
    if authenticated is None:
        raise HTTPException(status_code=401, detail="invalid session")
    session.commit()
    return _render_session(response, authenticated)


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


@router.get(
    "/workspaces/{workspace_id}/members",
    response_model=list[WorkspaceMemberManagementRead],
)
def list_members(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[WorkspaceMemberManagementRead]:
    context = _member_management_context(
        session,
        workspace_id,
        session_token,
    )
    members = WorkspaceMemberRepository(
        session,
        context=context,
    ).list_ordered()
    access_codes = WorkspaceAccessCodeRepository(
        session,
        context=context,
    ).list_for_members([member.id for member in members])
    revoked_by_member = {
        code.member_id: code.revoked_at is not None
        for code in access_codes
        if code.member_id is not None
    }
    return [
        WorkspaceMemberManagementRead(
            id=member.id,
            workspace_id=member.workspace_id,
            display_name=member.display_name,
            role=member.role.value,
            status="revoked" if member.revoked_at is not None else "active",
            last_access_at=None,
            last_access_status="not_recorded",
            invite_status=(
                "revoked"
                if member.revoked_at is not None
                or revoked_by_member.get(member.id, False)
                else "redeemed"
            ),
        )
        for member in members
    ]


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
