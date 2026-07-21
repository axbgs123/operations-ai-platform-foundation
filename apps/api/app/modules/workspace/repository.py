from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.workspace.models import (
    WorkspaceAccessCode,
    WorkspaceMember,
    WorkspaceSession,
)


ScopedModel = TypeVar("ScopedModel")


class WorkspaceScopedRepository(Generic[ScopedModel]):
    model: type[ScopedModel]

    def __init__(self, session: Session, *, context: WorkspaceContext) -> None:
        if context is None:
            raise ValueError("workspace context is required")
        self._session = session
        self._context = context

    def get(self, resource_id: UUID) -> ScopedModel | None:
        statement = select(self.model).where(
            self.model.id == resource_id,  # type: ignore[attr-defined]
            self.model.workspace_id  # type: ignore[attr-defined]
            == self._context.workspace_id,
        )
        return self._session.scalar(statement)

    def list(self) -> list[ScopedModel]:
        statement = select(self.model).where(
            self.model.workspace_id  # type: ignore[attr-defined]
            == self._context.workspace_id
        )
        return list(self._session.scalars(statement))


class WorkspaceMemberRepository(WorkspaceScopedRepository[WorkspaceMember]):
    model = WorkspaceMember


class WorkspaceAccessCodeRepository(
    WorkspaceScopedRepository[WorkspaceAccessCode]
):
    model = WorkspaceAccessCode

    def list_for_member(self, member_id: UUID) -> list[WorkspaceAccessCode]:
        statement = select(WorkspaceAccessCode).where(
            WorkspaceAccessCode.workspace_id == self._context.workspace_id,
            WorkspaceAccessCode.member_id == member_id,
        )
        return list(self._session.scalars(statement))


class AuthenticationRepository:
    """Narrow pre-authentication lookups; never exposes collection queries."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_access_code(self, code_id: UUID) -> WorkspaceAccessCode | None:
        return self._session.get(WorkspaceAccessCode, code_id)

    def get_session_by_token_hash(self, token_hash: str) -> WorkspaceSession | None:
        statement = select(WorkspaceSession).where(
            WorkspaceSession.token_hash == token_hash
        )
        return self._session.scalar(statement)

    def get_member(self, member_id: UUID) -> WorkspaceMember | None:
        return self._session.get(WorkspaceMember, member_id)
