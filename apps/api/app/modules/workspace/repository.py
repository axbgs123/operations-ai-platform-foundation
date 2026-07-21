from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.workspace.models import WorkspaceMember


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
