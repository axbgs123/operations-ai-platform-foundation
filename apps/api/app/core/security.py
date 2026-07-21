from dataclasses import dataclass
from typing import Literal
from uuid import UUID


WorkspaceRole = Literal["admin", "editor", "viewer", "demo"]


@dataclass(frozen=True)
class WorkspaceContext:
    workspace_id: UUID
    member_id: UUID | None
    role: WorkspaceRole
