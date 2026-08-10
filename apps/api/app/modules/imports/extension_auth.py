import hashlib
import secrets
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext, WorkspaceRole
from app.modules.imports.models import (
    ExtensionDeviceBinding,
    ExtensionToken,
    ExtensionTokenScope,
)
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.models import Workspace, WorkspaceMember


@dataclass(frozen=True)
class IssuedExtensionToken:
    token_id: UUID
    access_token: str
    workspace_id: UUID
    member_id: UUID
    client_id: str
    scopes: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class AuthenticatedExtension:
    token_id: UUID
    workspace_id: UUID
    member_id: UUID
    client_id: str
    scopes: tuple[str, ...]
    expires_at: datetime
    context: WorkspaceContext


class ExtensionTokenService:
    lifetime = timedelta(hours=8)

    def __init__(
        self,
        session: Session,
        *,
        now: Callable[[], datetime] | None = None,
        attempts: dict[str, deque[datetime]] | None = None,
    ) -> None:
        self._session = session
        self._now = now or (lambda: datetime.now(UTC))
        self._attempts = attempts if attempts is not None else defaultdict(deque)

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def bind(
        self,
        invite_code: str,
        *,
        client_id: str,
        display_name: str,
        client_key: str,
    ) -> IssuedExtensionToken:
        member = InviteAuthService(
            self._session,
            attempts=self._attempts,
        ).redeem_member(
            invite_code,
            display_name=display_name,
            client_key=client_key,
        )
        return self.issue(
            workspace_id=member.workspace_id,
            member_id=member.id,
            client_id=client_id,
        )

    def issue(
        self,
        *,
        workspace_id: UUID,
        member_id: UUID,
        client_id: str,
        device_id: UUID | None = None,
        now: datetime | None = None,
        lifetime: timedelta | None = None,
    ) -> IssuedExtensionToken:
        issued_at = now or self._now()
        expires_at = issued_at + (lifetime or self.lifetime)
        access_token = secrets.token_urlsafe(32)
        scopes = tuple(
            scope.value
            for scope in (
                ExtensionTokenScope.CAPTURE_CREATE,
                ExtensionTokenScope.CAPTURE_UPLOAD,
                ExtensionTokenScope.CAPTURE_READ,
            )
        )
        record = ExtensionToken(
            workspace_id=workspace_id,
            member_id=member_id,
            device_id=device_id,
            token_hash=self._digest(access_token),
            client_id=client_id,
            exchange_fingerprint=self._digest(f"issued:{access_token}"),
            scopes=list(scopes),
            issued_at=issued_at,
            expires_at=expires_at,
        )
        self._session.add(record)
        self._session.flush()
        return IssuedExtensionToken(
            token_id=record.id,
            access_token=access_token,
            workspace_id=workspace_id,
            member_id=member_id,
            client_id=client_id,
            scopes=scopes,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    def authenticate(
        self,
        access_token: str,
        *,
        required_scope: ExtensionTokenScope | None = None,
        workspace_id: UUID | None = None,
        member_id: UUID | None = None,
        now: datetime | None = None,
    ) -> AuthenticatedExtension | None:
        record = self._session.scalar(
            select(ExtensionToken).where(
                ExtensionToken.token_hash == self._digest(access_token)
            )
        )
        current = now or self._now()
        if (
            record is None
            or record.revoked_at is not None
            or record.expires_at <= current
            or (workspace_id is not None and record.workspace_id != workspace_id)
            or (member_id is not None and record.member_id != member_id)
            or (
                required_scope is not None
                and required_scope.value not in record.scopes
            )
        ):
            return None
        member = self._session.get(WorkspaceMember, record.member_id)
        if (
            member is None
            or member.workspace_id != record.workspace_id
            or member.revoked_at is not None
        ):
            return None
        if record.device_id is not None:
            device = self._session.get(ExtensionDeviceBinding, record.device_id)
            workspace = self._session.get(Workspace, record.workspace_id)
            if (
                device is None
                or device.workspace_id != record.workspace_id
                or device.member_id != record.member_id
                or device.revoked_at is not None
                or workspace is None
                or workspace.status != "active"
            ):
                return None
        context = WorkspaceContext(
            workspace_id=record.workspace_id,
            member_id=record.member_id,
            role=cast(WorkspaceRole, member.role.value),
        )
        return AuthenticatedExtension(
            token_id=record.id,
            workspace_id=record.workspace_id,
            member_id=record.member_id,
            client_id=record.client_id,
            scopes=tuple(record.scopes),
            expires_at=record.expires_at,
            context=context,
        )

    def revoke(self, token_id: UUID) -> None:
        record = self._session.get(ExtensionToken, token_id)
        if record is not None and record.revoked_at is None:
            record.revoked_at = self._now()
            self._session.flush()


__all__ = [
    "AuthenticatedExtension",
    "ExtensionToken",
    "ExtensionTokenScope",
    "ExtensionTokenService",
    "IssuedExtensionToken",
]
