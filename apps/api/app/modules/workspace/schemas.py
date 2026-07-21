from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


class WorkspaceMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    display_name: str
    role: Literal["admin", "editor", "viewer", "demo"]
    revoked_at: datetime | None


class WorkspaceCreated(BaseModel):
    workspace_id: UUID
    admin_code: str


class InviteLogin(BaseModel):
    code: str = Field(min_length=1, max_length=500)
    display_name: str = Field(min_length=1, max_length=80)


class SessionCreated(BaseModel):
    workspace_id: UUID
    member_id: UUID
    csrf_token: str


class MemberCodeCreate(BaseModel):
    role: Literal["admin", "editor", "viewer"]


class MemberCodeCreated(BaseModel):
    code: str
    role: Literal["admin", "editor", "viewer"]


class WorkspaceMemberUpdate(BaseModel):
    role: Literal["admin", "editor", "viewer"] | None = None
    revoked: Literal[True] | None = None

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if self.role is None and self.revoked is None:
            raise ValueError("role or revoked is required")
        return self
