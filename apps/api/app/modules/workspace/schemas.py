from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class WorkspaceOwnerOnboard(BaseModel):
    workspace_name: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("workspace_name", "display_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized


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


class WorkspaceMemberManagementRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    workspace_id: UUID
    display_name: str
    role: Literal["admin", "editor", "viewer", "demo"]
    status: Literal["active", "revoked"]
    last_access_at: datetime | None
    last_access_status: Literal["not_recorded"]
    invite_status: Literal["redeemed", "revoked"]


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
