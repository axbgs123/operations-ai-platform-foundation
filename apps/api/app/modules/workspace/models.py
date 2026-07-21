from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Enum, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import (
    Base,
    TimestampMixin,
    UTCDateTime,
    UUIDPrimaryKeyMixin,
    utc_now,
)


class MemberRole(StrEnum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"
    DEMO = "demo"


role_type = Enum(
    MemberRole,
    name="workspace_member_role",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)


class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(120))


class WorkspaceMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_members"
    __table_args__ = (Index("ix_workspace_members_workspace_id", "workspace_id"),)

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    display_name: Mapped[str] = mapped_column(String(80))
    role: Mapped[MemberRole] = mapped_column(role_type)
    revoked_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        default=None,
    )


class WorkspaceAccessCode(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_access_codes"
    __table_args__ = (Index("ix_access_codes_workspace_id", "workspace_id"),)

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    code_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[MemberRole] = mapped_column(role_type)
    member_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        default=None,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        default=None,
    )


class WorkspaceSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_sessions"
    __table_args__ = (
        Index("ix_workspace_sessions_token_hash", "token_hash", unique=True),
        Index("ix_workspace_sessions_workspace_id", "workspace_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    member_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="CASCADE"),
    )
    token_hash: Mapped[str] = mapped_column(String(64))
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        default=None,
    )


class AuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_workspace_id", "workspace_id"),)

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(100))
    member_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )
    resource_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        default=None,
    )
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default_factory=dict)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        init=False,
        default_factory=utc_now,
    )
