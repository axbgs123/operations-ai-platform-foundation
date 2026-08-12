from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import utc_now
from app.core.security import WorkspaceContext
from app.modules.operations_agent.models import (
    AgentChatMessage,
    AgentChatMessageKind,
    AgentChatRole,
    AgentChatSession,
    AgentChatStatus,
)
from app.modules.workspace.permissions import Permission, require_permission


@dataclass(frozen=True)
class AgentChatDetail:
    id: UUID
    workspace_id: UUID
    owner_member_id: UUID
    title: str
    status: str
    created_at: datetime
    updated_at: datetime
    messages: tuple[AgentChatMessage, ...]


class AgentChatService:
    def __init__(self, session: Session, context: WorkspaceContext) -> None:
        if context.member_id is None:
            raise ValueError("chat requires a workspace member")
        self._session = session
        self._context = context
        self._member_id = context.member_id

    def create(self, *, idempotency_key: str) -> AgentChatSession:
        self._require_write()
        key = self._key(idempotency_key)
        existing = self._session.scalar(
            select(AgentChatSession).where(
                AgentChatSession.workspace_id == self._context.workspace_id,
                AgentChatSession.idempotency_key == key,
            )
        )
        if existing is not None:
            if existing.owner_member_id != self._member_id:
                raise ValueError("idempotency key conflict")
            return existing
        chat = AgentChatSession(
            workspace_id=self._context.workspace_id,
            owner_member_id=self._member_id,
            idempotency_key=key,
        )
        self._session.add(chat)
        self._session.flush()
        return chat

    def list(self, *, page: int = 1, page_size: int = 30) -> list[AgentChatSession]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("invalid pagination")
        return list(
            self._session.scalars(
                select(AgentChatSession)
                .where(
                    AgentChatSession.workspace_id == self._context.workspace_id,
                    AgentChatSession.owner_member_id == self._member_id,
                )
                .order_by(
                    AgentChatSession.updated_at.desc(),
                    AgentChatSession.id.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )

    def read(
        self,
        chat_id: UUID,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> AgentChatDetail:
        require_permission(self._context.role, Permission.READ_CONTENT)
        chat = self._owned(chat_id, lock=False)
        if after_sequence < 0 or not 1 <= limit <= 200:
            raise ValueError("invalid message pagination")
        messages = tuple(
            self._session.scalars(
                select(AgentChatMessage)
                .where(
                    AgentChatMessage.workspace_id == self._context.workspace_id,
                    AgentChatMessage.session_id == chat.id,
                    AgentChatMessage.owner_member_id == self._member_id,
                    AgentChatMessage.sequence_no > after_sequence,
                )
                .order_by(AgentChatMessage.sequence_no, AgentChatMessage.id)
                .limit(limit)
            )
        )
        return AgentChatDetail(
            id=chat.id,
            workspace_id=chat.workspace_id,
            owner_member_id=chat.owner_member_id,
            title=chat.title,
            status=chat.status.value,
            created_at=chat.created_at,
            updated_at=chat.updated_at,
            messages=messages,
        )

    def append_user_message(
        self,
        chat_id: UUID,
        *,
        content: str,
        idempotency_key: str,
    ) -> AgentChatMessage:
        return self.append_message(
            chat_id,
            content=content,
            idempotency_key=idempotency_key,
            role=AgentChatRole.USER,
            kind=AgentChatMessageKind.TEXT,
        )

    def message_by_key(self, idempotency_key: str) -> AgentChatMessage | None:
        require_permission(self._context.role, Permission.READ_CONTENT)
        key = self._key(idempotency_key)
        return self._session.scalar(
            select(AgentChatMessage).where(
                AgentChatMessage.workspace_id == self._context.workspace_id,
                AgentChatMessage.owner_member_id == self._member_id,
                AgentChatMessage.idempotency_key == key,
            )
        )

    def append_message(
        self,
        chat_id: UUID,
        *,
        content: str,
        idempotency_key: str,
        role: AgentChatRole,
        kind: AgentChatMessageKind,
        plan_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> AgentChatMessage:
        self._require_write()
        normalized = self._content(content)
        key = self._key(idempotency_key)
        existing = self._session.scalar(
            select(AgentChatMessage).where(
                AgentChatMessage.workspace_id == self._context.workspace_id,
                AgentChatMessage.idempotency_key == key,
            )
        )
        if existing is not None:
            if (
                existing.session_id != chat_id
                or existing.owner_member_id != self._member_id
                or existing.content != normalized
                or existing.role is not role
                or existing.kind is not kind
            ):
                raise ValueError("idempotency key conflict")
            return existing
        chat = self._owned(chat_id, lock=True)
        if chat.status is AgentChatStatus.ARCHIVED:
            raise ValueError("archived chat cannot accept messages")
        sequence = int(
            self._session.scalar(
                select(func.coalesce(func.max(AgentChatMessage.sequence_no), 0))
                .where(AgentChatMessage.session_id == chat.id)
            )
            or 0
        ) + 1
        message = AgentChatMessage(
            workspace_id=self._context.workspace_id,
            session_id=chat.id,
            owner_member_id=self._member_id,
            sequence_no=sequence,
            idempotency_key=key,
            role=role,
            kind=kind,
            content=normalized,
            plan_id=plan_id,
            run_id=run_id,
        )
        self._session.add(message)
        if sequence == 1 and role is AgentChatRole.USER:
            chat.title = normalized[:60]
        chat.updated_at = utc_now()
        self._session.flush()
        return message

    def archive(self, chat_id: UUID) -> AgentChatSession:
        self._require_write()
        chat = self._owned(chat_id, lock=True)
        if chat.status is AgentChatStatus.ACTIVE:
            chat.status = AgentChatStatus.ARCHIVED
            chat.archived_at = utc_now()
            chat.updated_at = chat.archived_at
            self._session.flush()
        return chat

    def _owned(self, chat_id: UUID, *, lock: bool) -> AgentChatSession:
        query = select(AgentChatSession).where(
            AgentChatSession.id == chat_id,
            AgentChatSession.workspace_id == self._context.workspace_id,
            AgentChatSession.owner_member_id == self._member_id,
        )
        if lock:
            query = query.with_for_update()
        chat = self._session.scalar(query)
        if chat is None:
            raise LookupError("chat not found")
        return chat

    def _require_write(self) -> None:
        require_permission(self._context.role, Permission.WRITE_CONTENT)

    @staticmethod
    def _key(value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 200:
            raise ValueError("invalid idempotency key")
        return normalized

    @staticmethod
    def _content(value: str) -> str:
        normalized = re.sub(r"\s+", " ", value).strip()
        if not normalized:
            raise ValueError("message cannot be empty")
        if len(normalized) > 4000:
            raise ValueError("message exceeds 4000 characters")
        return normalized
