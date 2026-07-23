import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from app.modules.content.account_models import Platform
from app.modules.risk_rag.models import (
    RiskAuthorizationStatus,
    RiskChunk,
    RiskChunkEmbedding,
    RiskDocument,
    RiskDocumentScope,
    RiskDocumentStatus,
    RiskSourceLevel,
)


NO_ACTIVE_RISK_EVIDENCE = "NO_ACTIVE_RISK_EVIDENCE"
ACTIVE_RISK_EVIDENCE = "ACTIVE_RISK_EVIDENCE"
MAX_TOP_K = 100


@dataclass(frozen=True)
class RetrievalFilter:
    workspace_id: UUID
    platform: Platform
    as_of: datetime
    embedding_model_id: str
    embedding_version: str
    embedding_dimension: int

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        if not self.embedding_model_id.strip():
            raise ValueError("embedding_model_id is required")
        if not self.embedding_version.strip():
            raise ValueError("embedding_version is required")
        if self.embedding_dimension <= 0:
            raise ValueError("embedding_dimension must be positive")


@dataclass(frozen=True)
class SecurityDiagnostic:
    code: str
    detail: str
    chunk_id: UUID | None = None


@dataclass(frozen=True)
class EvidenceChunk:
    chunk_id: UUID
    document_id: UUID
    document_title: str
    source_level: RiskSourceLevel
    source_url: str | None
    private_document_id: str | None
    document_version: int
    effective_at: datetime
    platform: Platform
    workspace_id: UUID | None
    scope: RiskDocumentScope
    source_location: str
    untrusted_text: str
    similarity: float


@dataclass(frozen=True)
class EvidenceBundle:
    retrieval_filter: RetrievalFilter
    evidence: tuple[EvidenceChunk, ...]
    status: str | None = None
    diagnostics: tuple[SecurityDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        expected_status = (
            ACTIVE_RISK_EVIDENCE
            if self.evidence
            else NO_ACTIVE_RISK_EVIDENCE
        )
        if self.status is None:
            object.__setattr__(self, "status", expected_status)
        elif self.status != expected_status:
            raise ValueError("evidence bundle status does not match evidence")

        seen: set[UUID] = set()
        for item in self.evidence:
            if item.chunk_id in seen:
                raise ValueError("evidence bundle contains duplicate chunk")
            seen.add(item.chunk_id)
            if item.platform is not self.retrieval_filter.platform:
                raise ValueError("evidence platform does not match filter")
            if item.scope is RiskDocumentScope.PUBLIC:
                if item.workspace_id is not None:
                    raise ValueError("public evidence cannot have workspace")
            elif item.workspace_id != self.retrieval_filter.workspace_id:
                raise ValueError("private evidence workspace does not match filter")

    def by_chunk_id(self) -> dict[UUID, EvidenceChunk]:
        return {item.chunk_id: item for item in self.evidence}


def _eligible_metadata_statement(
    retrieval_filter: RetrievalFilter,
) -> Select[Any]:
    public_scope = and_(
        RiskDocument.scope == RiskDocumentScope.PUBLIC,
        RiskDocument.workspace_id.is_(None),
        RiskChunk.scope == RiskDocumentScope.PUBLIC,
        RiskChunk.workspace_id.is_(None),
        RiskChunkEmbedding.scope == RiskDocumentScope.PUBLIC,
        RiskChunkEmbedding.workspace_id.is_(None),
        or_(
            RiskDocument.source_level.in_(
                (RiskSourceLevel.S1, RiskSourceLevel.S2)
            ),
            RiskDocument.authorization_status
            == RiskAuthorizationStatus.AUTHORIZED,
        ),
    )
    private_scope = and_(
        RiskDocument.scope == RiskDocumentScope.PRIVATE,
        RiskDocument.workspace_id == retrieval_filter.workspace_id,
        RiskChunk.scope == RiskDocumentScope.PRIVATE,
        RiskChunk.workspace_id == retrieval_filter.workspace_id,
        RiskChunkEmbedding.scope == RiskDocumentScope.PRIVATE,
        RiskChunkEmbedding.workspace_id == retrieval_filter.workspace_id,
    )
    return (
        select(
            RiskChunk.id.label("chunk_id"),
            RiskDocument.id.label("document_id"),
            RiskDocument.title.label("document_title"),
            RiskDocument.source_level.label("source_level"),
            RiskDocument.source_url.label("source_url"),
            RiskDocument.private_document_id.label("private_document_id"),
            RiskDocument.version.label("document_version"),
            RiskDocument.effective_at.label("effective_at"),
            RiskDocument.platform.label("platform"),
            RiskDocument.workspace_id.label("workspace_id"),
            RiskDocument.scope.label("scope"),
            RiskChunk.chunk_index.label("chunk_index"),
            RiskChunk.source_location.label("source_location"),
            RiskChunk.text.label("untrusted_text"),
            RiskChunkEmbedding.vector.label("vector"),
        )
        .select_from(RiskChunkEmbedding)
        .join(RiskChunk, RiskChunk.id == RiskChunkEmbedding.chunk_id)
        .join(RiskDocument, RiskDocument.id == RiskChunk.document_id)
        .where(
            or_(public_scope, private_scope),
            RiskDocument.platform == retrieval_filter.platform,
            RiskChunk.platform == retrieval_filter.platform,
            RiskChunkEmbedding.platform == retrieval_filter.platform,
            RiskDocument.status == RiskDocumentStatus.ACTIVE,
            RiskDocument.effective_at.is_not(None),
            RiskDocument.effective_at <= retrieval_filter.as_of,
            RiskDocument.authorization_status
            != RiskAuthorizationStatus.RESTRICTED,
            RiskChunkEmbedding.model_id
            == retrieval_filter.embedding_model_id,
            RiskChunkEmbedding.embedding_version
            == retrieval_filter.embedding_version,
            RiskChunkEmbedding.dimension
            == retrieval_filter.embedding_dimension,
        )
    )


def build_pgvector_retrieval_statement(
    *,
    retrieval_filter: RetrievalFilter,
    query_vector: tuple[float, ...],
    top_k: int,
) -> Select[Any]:
    _validate_query(
        retrieval_filter=retrieval_filter,
        query_vector=query_vector,
        top_k=top_k,
    )
    eligible = (
        _eligible_metadata_statement(retrieval_filter)
        .cte("eligible_risk_evidence")
        .prefix_with("MATERIALIZED", dialect="postgresql")
    )
    distance = eligible.c.vector.cosine_distance(list(query_vector))
    return (
        select(*eligible.c, distance.label("distance"))
        .order_by(distance, eligible.c.chunk_id)
        .limit(top_k)
    )


def _validate_query(
    *,
    retrieval_filter: RetrievalFilter,
    query_vector: tuple[float, ...],
    top_k: int,
) -> None:
    if not 1 <= top_k <= MAX_TOP_K:
        raise ValueError(f"top_k must be between 1 and {MAX_TOP_K}")
    if len(query_vector) != retrieval_filter.embedding_dimension:
        raise ValueError("query vector dimension does not match filter")
    if not all(math.isfinite(value) for value in query_vector):
        raise ValueError("query vector must contain finite values")
    if math.isclose(sum(value * value for value in query_vector), 0.0):
        raise ValueError("query vector must not be zero")


def _cosine_similarity(
    query_vector: tuple[float, ...],
    candidate_vector: list[float],
) -> float:
    query_norm = math.sqrt(sum(value * value for value in query_vector))
    candidate_norm = math.sqrt(
        sum(float(value) * float(value) for value in candidate_vector)
    )
    if math.isclose(candidate_norm, 0.0):
        return -1.0
    dot_product = sum(
        query * float(candidate)
        for query, candidate in zip(query_vector, candidate_vector, strict=True)
    )
    return dot_product / (query_norm * candidate_norm)


def _to_evidence(row: Any, *, similarity: float) -> EvidenceChunk:
    effective_at = row.effective_at
    if effective_at is None:
        raise ValueError("eligible evidence must have an effective date")
    return EvidenceChunk(
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        document_title=row.document_title,
        source_level=row.source_level,
        source_url=row.source_url,
        private_document_id=row.private_document_id,
        document_version=row.document_version,
        effective_at=effective_at,
        platform=row.platform,
        workspace_id=row.workspace_id,
        scope=row.scope,
        source_location=row.source_location,
        untrusted_text=row.untrusted_text,
        similarity=similarity,
    )


class RiskEvidenceRetriever:
    def __init__(self, session: Session) -> None:
        self._session = session

    def retrieve(
        self,
        *,
        retrieval_filter: RetrievalFilter,
        query_vector: tuple[float, ...],
        top_k: int,
    ) -> EvidenceBundle:
        _validate_query(
            retrieval_filter=retrieval_filter,
            query_vector=query_vector,
            top_k=top_k,
        )
        if self._session.bind is not None and (
            self._session.bind.dialect.name == "postgresql"
        ):
            statement = build_pgvector_retrieval_statement(
                retrieval_filter=retrieval_filter,
                query_vector=query_vector,
                top_k=top_k,
            )
            rows = self._session.execute(statement)
            evidence = tuple(
                _to_evidence(row, similarity=1.0 - float(row.distance))
                for row in rows
            )
        else:
            candidates = self._session.execute(
                _eligible_metadata_statement(retrieval_filter)
            )
            ranked = sorted(
                (
                    (
                        _cosine_similarity(
                            query_vector,
                            [float(value) for value in row.vector],
                        ),
                        row,
                    )
                    for row in candidates
                ),
                key=lambda pair: (-pair[0], str(pair[1].chunk_id)),
            )[:top_k]
            evidence = tuple(
                _to_evidence(row, similarity=similarity)
                for similarity, row in ranked
            )
        return EvidenceBundle(
            retrieval_filter=retrieval_filter,
            evidence=evidence,
        )
