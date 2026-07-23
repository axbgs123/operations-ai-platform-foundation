from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.content.account_models import Platform
from app.modules.risk_rag.models import (
    RiskAuthorizationStatus,
    RiskChunk,
    RiskDocument,
    RiskDocumentScope,
    RiskDocumentStatus,
    RiskSourceLevel,
)
from app.modules.risk_rag.lifecycle import (
    transition_status,
    validate_source_policy,
)
from app.modules.workspace.permissions import (
    Permission,
    PermissionDenied,
    require_permission,
)


class RiskDocumentRepository:
    def __init__(self, session: Session, *, context: WorkspaceContext) -> None:
        if context is None:
            raise ValueError("workspace context is required")
        self._session = session
        self._context = context

    def _visible_document_clause(self):
        return or_(
            RiskDocument.scope == RiskDocumentScope.PUBLIC,
            RiskDocument.workspace_id == self._context.workspace_id,
        )

    def _visible_chunk_clause(self):
        return or_(
            RiskChunk.scope == RiskDocumentScope.PUBLIC,
            RiskChunk.workspace_id == self._context.workspace_id,
        )

    def get(self, document_id: UUID) -> RiskDocument | None:
        statement = select(RiskDocument).where(
            RiskDocument.id == document_id,
            self._visible_document_clause(),
        )
        return self._session.scalar(statement)

    def get_historical(self, document_id: UUID) -> RiskDocument | None:
        return self.get(document_id)

    def add_private(
        self,
        *,
        platform: Platform,
        source_level: RiskSourceLevel,
        title: str,
        private_document_id: str,
        authorization_status: RiskAuthorizationStatus,
        published_at: datetime | None,
        effective_at: datetime | None,
        accessed_at: datetime | None,
    ) -> RiskDocument:
        require_permission(
            self._context.role,
            Permission.MANAGE_RISK_KNOWLEDGE,
        )
        validate_source_policy(
            scope=RiskDocumentScope.PRIVATE,
            level=source_level,
            authorization_status=authorization_status,
            workspace_id=self._context.workspace_id,
        )
        document = RiskDocument(
            workspace_id=self._context.workspace_id,
            platform=platform,
            scope=RiskDocumentScope.PRIVATE,
            source_level=source_level,
            title=title,
            private_document_id=private_document_id,
            authorization_status=authorization_status,
            status=RiskDocumentStatus.DRAFT,
            version=1,
            published_at=published_at,
            effective_at=effective_at,
            accessed_at=accessed_at,
        )
        self._session.add(document)
        self._session.flush()
        return document

    def transition(
        self,
        document_id: UUID,
        target: RiskDocumentStatus,
    ) -> RiskDocument | None:
        document = self.get(document_id)
        if document is None:
            return None
        require_permission(
            self._context.role,
            Permission.MANAGE_RISK_KNOWLEDGE,
        )
        if document.scope is RiskDocumentScope.PUBLIC:
            raise PermissionDenied(
                "system public risk library cannot be changed by a workspace"
            )
        reviewer_id = (
            self._context.member_id
            if target is RiskDocumentStatus.ACTIVE
            else document.reviewed_by
        )
        if document.status is target:
            return document
        document.status = transition_status(
            document.status,
            target,
            reviewer_id=reviewer_id,
        )
        if target is RiskDocumentStatus.ACTIVE:
            document.reviewed_by = reviewer_id
        self._session.flush()
        return document

    def list_current(
        self,
        *,
        platform: Platform,
        at: datetime,
    ) -> list[RiskDocument]:
        statement = (
            select(RiskDocument)
            .where(
                self._visible_document_clause(),
                RiskDocument.platform == platform,
                RiskDocument.status == RiskDocumentStatus.ACTIVE,
                RiskDocument.effective_at.is_not(None),
                RiskDocument.effective_at <= at,
            )
            .order_by(RiskDocument.created_at, RiskDocument.id)
        )
        return list(self._session.scalars(statement))

    def list_visible(
        self,
        *,
        platform: Platform | None = None,
    ) -> list[RiskDocument]:
        statement = select(RiskDocument).where(self._visible_document_clause())
        if platform is not None:
            statement = statement.where(RiskDocument.platform == platform)
        return list(
            self._session.scalars(
                statement.order_by(RiskDocument.created_at, RiskDocument.id)
            )
        )

    def parse_inline(
        self,
        document_id: UUID,
        *,
        text: str,
        source_location: str,
    ) -> RiskDocument | None:
        require_permission(
            self._context.role,
            Permission.MANAGE_RISK_KNOWLEDGE,
        )
        document = self.get(document_id)
        if document is None:
            return None
        if document.scope is RiskDocumentScope.PUBLIC:
            raise PermissionDenied(
                "system public risk library cannot be changed by a workspace"
            )
        if document.status is RiskDocumentStatus.PARSED:
            return document
        if not text.strip():
            raise ValueError("risk document text cannot be empty")
        document.status = transition_status(
            document.status,
            RiskDocumentStatus.PARSED,
            reviewer_id=None,
        )
        self._session.add(
            RiskChunk(
                workspace_id=document.workspace_id,
                document_id=document.id,
                platform=document.platform,
                scope=document.scope,
                chunk_index=0,
                source_location=source_location,
                text=text,
                metadata_json={"untrusted_data": True, "inline": True},
            )
        )
        self._session.flush()
        return document

    def list_chunks(self, document_id: UUID) -> list[RiskChunk]:
        if self.get(document_id) is None:
            return []
        statement = (
            select(RiskChunk)
            .where(
                RiskChunk.document_id == document_id,
                self._visible_chunk_clause(),
            )
            .order_by(RiskChunk.chunk_index)
        )
        return list(self._session.scalars(statement))

    def version_chain(self, document_id: UUID) -> list[RiskDocument]:
        chain: list[RiskDocument] = []
        seen: set[UUID] = set()
        current = self.get_historical(document_id)
        while current is not None and current.id not in seen:
            chain.append(current)
            seen.add(current.id)
            if current.previous_version_id is None:
                break
            current = self.get_historical(current.previous_version_id)
        return chain
