from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.core.database import Base
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
from app.modules.risk_rag.retrieval import (
    NO_ACTIVE_RISK_EVIDENCE,
    RiskEvidenceRetriever,
    RetrievalFilter,
    build_pgvector_retrieval_statement,
)
from app.modules.workspace.models import Workspace


pytestmark = pytest.mark.isolation


NOW = datetime(2026, 7, 23, 8, tzinfo=UTC)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        yield database_session


def _add_evidence(
    session: Session,
    *,
    workspace_id: UUID | None,
    platform: Platform = Platform.DOUYIN,
    scope: RiskDocumentScope = RiskDocumentScope.PRIVATE,
    status: RiskDocumentStatus = RiskDocumentStatus.ACTIVE,
    effective_at: datetime | None = NOW - timedelta(days=1),
    title: str,
    text: str | None = None,
    model_id: str = "mock-risk-embedding",
    embedding_version: str = "v1",
    vector: tuple[float, ...] = (1.0, 0.0, 0.0),
    declared_dimension: int | None = None,
    source_level: RiskSourceLevel = RiskSourceLevel.S3,
) -> RiskChunk:
    reference = title.lower().replace(" ", "-")
    document = RiskDocument(
        workspace_id=workspace_id,
        platform=platform,
        scope=scope,
        source_level=source_level,
        title=title,
        source_url=(
            f"https://example.invalid/{reference}"
            if scope is RiskDocumentScope.PUBLIC
            else None
        ),
        private_document_id=(
            f"synthetic-{reference}"
            if scope is RiskDocumentScope.PRIVATE
            else None
        ),
        authorization_status=RiskAuthorizationStatus.AUTHORIZED,
        status=status,
        version=1,
        effective_at=effective_at,
    )
    session.add(document)
    session.flush()
    chunk = RiskChunk(
        workspace_id=workspace_id,
        document_id=document.id,
        platform=platform,
        scope=scope,
        chunk_index=0,
        source_location="人工合成条款 1",
        text=text or f"{title}：人工合成证据正文。",
        metadata_json={"untrusted_data": True},
    )
    session.add(chunk)
    session.flush()
    session.add(
        RiskChunkEmbedding(
            workspace_id=workspace_id,
            chunk_id=chunk.id,
            platform=platform,
            scope=scope,
            model_id=model_id,
            dimension=declared_dimension or len(vector),
            embedding_version=embedding_version,
            vector=list(vector),
        )
    )
    session.flush()
    return chunk


def _retrieval_filter(
    workspace_id: UUID,
    *,
    platform: Platform = Platform.DOUYIN,
) -> RetrievalFilter:
    return RetrievalFilter(
        workspace_id=workspace_id,
        platform=platform,
        as_of=NOW,
        embedding_model_id="mock-risk-embedding",
        embedding_version="v1",
        embedding_dimension=3,
    )


def test_filter_is_structured_immutable_and_requires_all_trust_boundaries() -> None:
    workspace_id = Workspace(name="filter-workspace").id
    retrieval_filter = _retrieval_filter(workspace_id)

    with pytest.raises(FrozenInstanceError):
        retrieval_filter.platform = Platform.XIAOHONGSHU  # type: ignore[misc]
    with pytest.raises(TypeError):
        RetrievalFilter(  # type: ignore[call-arg]
            workspace_id=workspace_id,
            platform=Platform.DOUYIN,
        )
    with pytest.raises(ValueError, match="timezone"):
        RetrievalFilter(
            workspace_id=workspace_id,
            platform=Platform.DOUYIN,
            as_of=datetime(2026, 7, 23),
            embedding_model_id="mock-risk-embedding",
            embedding_version="v1",
            embedding_dimension=3,
        )


def test_retrieval_returns_only_public_and_current_workspace_active_evidence(
    session: Session,
) -> None:
    workspace = Workspace(name="current-workspace")
    other = Workspace(name="other-workspace")
    session.add_all([workspace, other])
    session.flush()
    allowed_private = _add_evidence(
        session,
        workspace_id=workspace.id,
        title="Current private",
    )
    allowed_public = _add_evidence(
        session,
        workspace_id=None,
        scope=RiskDocumentScope.PUBLIC,
        title="Public",
        source_level=RiskSourceLevel.S1,
        vector=(0.9, 0.1, 0.0),
    )
    excluded_titles = {
        "Other workspace",
        "Other platform",
        "Draft",
        "Parsed",
        "Pending review",
        "Superseded",
        "Expired",
        "Future",
        "Other model",
        "Other embedding version",
        "Other dimension",
    }
    _add_evidence(
        session,
        workspace_id=other.id,
        title="Other workspace",
    )
    _add_evidence(
        session,
        workspace_id=workspace.id,
        platform=Platform.XIAOHONGSHU,
        title="Other platform",
    )
    for status, title in (
        (RiskDocumentStatus.DRAFT, "Draft"),
        (RiskDocumentStatus.PARSED, "Parsed"),
        (RiskDocumentStatus.PENDING_REVIEW, "Pending review"),
        (RiskDocumentStatus.SUPERSEDED, "Superseded"),
        (RiskDocumentStatus.EXPIRED, "Expired"),
    ):
        _add_evidence(
            session,
            workspace_id=workspace.id,
            status=status,
            title=title,
        )
    _add_evidence(
        session,
        workspace_id=workspace.id,
        effective_at=NOW + timedelta(seconds=1),
        title="Future",
    )
    _add_evidence(
        session,
        workspace_id=workspace.id,
        model_id="mock-other-model",
        title="Other model",
    )
    _add_evidence(
        session,
        workspace_id=workspace.id,
        embedding_version="v2",
        title="Other embedding version",
    )
    _add_evidence(
        session,
        workspace_id=workspace.id,
        vector=(1.0, 0.0),
        declared_dimension=2,
        title="Other dimension",
    )
    session.commit()

    bundle = RiskEvidenceRetriever(session).retrieve(
        retrieval_filter=_retrieval_filter(workspace.id),
        query_vector=(1.0, 0.0, 0.0),
        top_k=20,
    )

    assert {item.chunk_id for item in bundle.evidence} == {
        allowed_private.id,
        allowed_public.id,
    }
    assert not excluded_titles.intersection(
        item.document_title for item in bundle.evidence
    )
    assert all(item.platform is Platform.DOUYIN for item in bundle.evidence)
    assert all(
        item.workspace_id in {None, workspace.id}
        for item in bundle.evidence
    )


@pytest.mark.parametrize(
    ("platform", "expected_title"),
    [
        (Platform.DOUYIN, "Douyin only"),
        (Platform.XIAOHONGSHU, "Xiaohongshu only"),
    ],
)
def test_platform_queries_never_cross_recall(
    session: Session,
    platform: Platform,
    expected_title: str,
) -> None:
    workspace = Workspace(name=f"platform-{platform.value}")
    session.add(workspace)
    session.flush()
    _add_evidence(
        session,
        workspace_id=workspace.id,
        platform=Platform.DOUYIN,
        title="Douyin only",
    )
    _add_evidence(
        session,
        workspace_id=workspace.id,
        platform=Platform.XIAOHONGSHU,
        title="Xiaohongshu only",
    )
    session.commit()

    bundle = RiskEvidenceRetriever(session).retrieve(
        retrieval_filter=_retrieval_filter(
            workspace.id,
            platform=platform,
        ),
        query_vector=(1.0, 0.0, 0.0),
        top_k=10,
    )

    assert [item.document_title for item in bundle.evidence] == [
        expected_title
    ]


def test_postgres_query_materializes_metadata_filter_before_vector_ranking() -> None:
    workspace_id = Workspace(name="sql-proof").id
    statement = build_pgvector_retrieval_statement(
        retrieval_filter=_retrieval_filter(workspace_id),
        query_vector=(1.0, 0.0, 0.0),
        top_k=5,
    )

    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    normalized = " ".join(sql.lower().split())
    vector_rank_position = normalized.index("<=>")
    assert "as materialized" in normalized
    for predicate in (
        "risk_documents.workspace_id",
        "risk_documents.platform",
        "risk_documents.status",
        "risk_documents.effective_at",
        "risk_chunk_embeddings.model_id",
        "risk_chunk_embeddings.embedding_version",
        "risk_chunk_embeddings.dimension",
    ):
        assert normalized.index(predicate) < vector_rank_position
    assert "order by eligible_risk_evidence.vector <=>" in normalized


def test_fixed_vectors_have_stable_tie_order_and_exact_top_k(
    session: Session,
) -> None:
    workspace = Workspace(name="stable-ranking")
    session.add(workspace)
    session.flush()
    exact = _add_evidence(
        session,
        workspace_id=workspace.id,
        title="Exact",
        vector=(1.0, 0.0, 0.0),
    )
    tied_a = _add_evidence(
        session,
        workspace_id=workspace.id,
        title="Tied A",
        vector=(0.8, 0.6, 0.0),
    )
    tied_b = _add_evidence(
        session,
        workspace_id=workspace.id,
        title="Tied B",
        vector=(0.8, 0.6, 0.0),
    )
    session.commit()
    expected_tie_order = sorted((tied_a.id, tied_b.id), key=str)

    result = RiskEvidenceRetriever(session).retrieve(
        retrieval_filter=_retrieval_filter(workspace.id),
        query_vector=(1.0, 0.0, 0.0),
        top_k=3,
    )
    bounded = RiskEvidenceRetriever(session).retrieve(
        retrieval_filter=_retrieval_filter(workspace.id),
        query_vector=(1.0, 0.0, 0.0),
        top_k=2,
    )

    assert [item.chunk_id for item in result.evidence] == [
        exact.id,
        *expected_tie_order,
    ]
    assert [item.chunk_id for item in bounded.evidence] == [
        exact.id,
        expected_tie_order[0],
    ]
    assert result.evidence[0].similarity == pytest.approx(1.0)
    assert result.evidence[1].similarity == pytest.approx(0.8)


@pytest.mark.parametrize("top_k", [0, -1, 101])
def test_top_k_bounds_are_rejected(
    session: Session,
    top_k: int,
) -> None:
    workspace_id = Workspace(name=f"top-k-{top_k}").id
    with pytest.raises(ValueError, match="top_k"):
        RiskEvidenceRetriever(session).retrieve(
            retrieval_filter=_retrieval_filter(workspace_id),
            query_vector=(1.0, 0.0, 0.0),
            top_k=top_k,
        )


def test_query_vector_dimension_must_match_filter(session: Session) -> None:
    workspace_id = Workspace(name="query-dimension").id
    with pytest.raises(ValueError, match="dimension"):
        RiskEvidenceRetriever(session).retrieve(
            retrieval_filter=_retrieval_filter(workspace_id),
            query_vector=(1.0, 0.0),
            top_k=5,
        )


def test_no_eligible_rows_return_explicit_no_evidence_result(
    session: Session,
) -> None:
    workspace = Workspace(name="no-evidence")
    session.add(workspace)
    session.commit()

    bundle = RiskEvidenceRetriever(session).retrieve(
        retrieval_filter=_retrieval_filter(workspace.id),
        query_vector=(1.0, 0.0, 0.0),
        top_k=5,
    )

    assert bundle.evidence == ()
    assert bundle.status == NO_ACTIVE_RISK_EVIDENCE
