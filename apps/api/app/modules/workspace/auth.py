import hashlib
import hmac
import secrets
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext, WorkspaceRole
from app.modules.workspace.models import (
    AuditLog,
    MemberRole,
    Workspace,
    WorkspaceAccessCode,
    WorkspaceMember,
    WorkspaceSession,
)
from app.modules.workspace.permissions import Permission, require_permission
from app.modules.workspace.repository import (
    AuthenticationRepository,
    WorkspaceAccessCodeRepository,
    WorkspaceMemberRepository,
)


class InvalidInviteCode(Exception):
    pass


class InviteRateLimitExceeded(Exception):
    pass


@dataclass(frozen=True)
class IssuedWorkspace:
    workspace_id: UUID
    admin_code: str


@dataclass(frozen=True)
class AuthenticatedSession:
    member_id: UUID
    session_token: str
    csrf_token: str
    expires_at: datetime
    context: WorkspaceContext


class InviteAuthService:
    def __init__(
        self,
        session: Session,
        *,
        now: Callable[[], datetime] | None = None,
        max_attempts: int = 10,
        attempt_window: timedelta = timedelta(minutes=1),
        session_lifetime: timedelta = timedelta(days=14),
        attempts: dict[str, deque[datetime]] | None = None,
    ) -> None:
        self._session = session
        self._now = now or (lambda: datetime.now(UTC))
        self._max_attempts = max_attempts
        self._attempt_window = attempt_window
        self._session_lifetime = session_lifetime
        self._attempts = attempts if attempts is not None else defaultdict(deque)
        self._password_hasher = PasswordHasher(
            time_cost=2,
            memory_cost=19_456,
            parallelism=1,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )
        self._authentication = AuthenticationRepository(session)

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def _record_attempt(self, client_key: str) -> None:
        attempts = self._attempts[client_key]
        cutoff = self._now() - self._attempt_window
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if len(attempts) >= self._max_attempts:
            raise InviteRateLimitExceeded
        attempts.append(self._now())

    def _issue_code(self, workspace_id: UUID, role: MemberRole) -> str:
        secret = secrets.token_urlsafe(32)
        access_code = WorkspaceAccessCode(
            workspace_id=workspace_id,
            code_hash=self._password_hasher.hash(secret),
            role=role,
        )
        self._session.add(access_code)
        return f"{access_code.id}.{secret}"

    def create_workspace(self, name: str) -> IssuedWorkspace:
        workspace = Workspace(name=name)
        self._session.add(workspace)
        self._session.flush()
        code = self._issue_code(workspace.id, MemberRole.ADMIN)
        self._session.add(
            AuditLog(
                workspace_id=workspace.id,
                action="invite.issued",
                resource_type="workspace_access_code",
                details={"role": "admin"},
            )
        )
        self._session.flush()
        return IssuedWorkspace(workspace_id=workspace.id, admin_code=code)

    def redeem(
        self,
        raw_code: str,
        *,
        display_name: str,
        client_key: str,
    ) -> AuthenticatedSession:
        self._record_attempt(client_key)
        try:
            raw_id, secret = raw_code.split(".", maxsplit=1)
            code_id = UUID(raw_id)
        except (ValueError, AttributeError) as error:
            raise InvalidInviteCode from error

        access_code = self._authentication.get_access_code(code_id)
        if access_code is None or access_code.revoked_at is not None:
            raise InvalidInviteCode
        if access_code.expires_at is not None and access_code.expires_at <= self._now():
            raise InvalidInviteCode
        try:
            self._password_hasher.verify(access_code.code_hash, secret)
        except (InvalidHashError, VerifyMismatchError) as error:
            raise InvalidInviteCode from error

        member = (
            self._authentication.get_member(access_code.member_id)
            if access_code.member_id is not None
            else None
        )
        if member is None:
            member = WorkspaceMember(
                workspace_id=access_code.workspace_id,
                display_name=display_name,
                role=access_code.role,
            )
            self._session.add(member)
            self._session.flush()
            access_code.member_id = member.id
        if member.revoked_at is not None:
            raise InvalidInviteCode
        self._session.flush()

        session_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = self._now() + self._session_lifetime
        self._session.add(
            WorkspaceSession(
                workspace_id=member.workspace_id,
                member_id=member.id,
                token_hash=self._digest(session_token),
                csrf_hash=self._digest(csrf_token),
                expires_at=expires_at,
            )
        )
        self._session.add(
            AuditLog(
                workspace_id=member.workspace_id,
                member_id=member.id,
                action="session.created",
                resource_type="workspace_session",
            )
        )
        self._session.flush()
        context = WorkspaceContext(
            workspace_id=member.workspace_id,
            member_id=member.id,
            role=cast(WorkspaceRole, member.role.value),
        )
        return AuthenticatedSession(
            member_id=member.id,
            session_token=session_token,
            csrf_token=csrf_token,
            expires_at=expires_at,
            context=context,
        )

    def authenticate(self, session_token: str) -> WorkspaceContext | None:
        stored_session = self._authentication.get_session_by_token_hash(
            self._digest(session_token)
        )
        if (
            stored_session is None
            or stored_session.revoked_at is not None
            or stored_session.expires_at <= self._now()
        ):
            return None
        member = self._authentication.get_member(stored_session.member_id)
        if member is None or member.revoked_at is not None:
            return None
        return WorkspaceContext(
            workspace_id=member.workspace_id,
            member_id=member.id,
            role=cast(WorkspaceRole, member.role.value),
        )

    def validate_csrf(self, session_token: str, csrf_token: str) -> bool:
        stored_session = self._authentication.get_session_by_token_hash(
            self._digest(session_token)
        )
        return stored_session is not None and hmac.compare_digest(
            stored_session.csrf_hash,
            self._digest(csrf_token),
        )

    def logout(self, session_token: str) -> None:
        stored_session = self._authentication.get_session_by_token_hash(
            self._digest(session_token)
        )
        if stored_session is None:
            return
        stored_session.revoked_at = self._now()
        self._session.add(
            AuditLog(
                workspace_id=stored_session.workspace_id,
                member_id=stored_session.member_id,
                action="session.revoked",
                resource_type="workspace_session",
                resource_id=stored_session.id,
            )
        )
        self._session.flush()

    def issue_member_code(
        self,
        context: WorkspaceContext,
        role: MemberRole,
    ) -> str:
        require_permission(context.role, Permission.MANAGE_MEMBERS)
        code = self._issue_code(context.workspace_id, role)
        self._session.add(
            AuditLog(
                workspace_id=context.workspace_id,
                member_id=context.member_id,
                action="invite.issued",
                resource_type="workspace_access_code",
                details={"role": role.value},
            )
        )
        self._session.flush()
        return code

    def update_member_role(
        self,
        context: WorkspaceContext,
        member_id: UUID,
        role: MemberRole,
    ) -> WorkspaceMember:
        require_permission(context.role, Permission.MANAGE_MEMBERS)
        member = WorkspaceMemberRepository(self._session, context=context).get(member_id)
        if member is None:
            raise LookupError("member not found")
        previous_role = member.role
        member.role = role
        self._session.add(
            AuditLog(
                workspace_id=context.workspace_id,
                member_id=context.member_id,
                action="member.role_changed",
                resource_type="workspace_member",
                resource_id=member.id,
                details={"from": previous_role.value, "to": role.value},
            )
        )
        self._session.flush()
        return member

    def revoke_member(
        self, context: WorkspaceContext, member_id: UUID
    ) -> WorkspaceMember:
        require_permission(context.role, Permission.MANAGE_MEMBERS)
        member = WorkspaceMemberRepository(
            self._session,
            context=context,
        ).get(member_id)
        if member is None:
            raise LookupError("member not found")
        member.revoked_at = self._now()
        access_codes = WorkspaceAccessCodeRepository(
            self._session,
            context=context,
        ).list_for_member(member.id)
        for access_code in access_codes:
            access_code.revoked_at = self._now()
            self._session.add(
                AuditLog(
                    workspace_id=context.workspace_id,
                    member_id=context.member_id,
                    action="invite.revoked",
                    resource_type="workspace_access_code",
                    resource_id=access_code.id,
                )
            )
        self._session.add(
            AuditLog(
                workspace_id=context.workspace_id,
                member_id=context.member_id,
                action="member.revoked",
                resource_type="workspace_member",
                resource_id=member.id,
            )
        )
        self._session.flush()
        return member
