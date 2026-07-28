from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.security import WorkspaceContext
from app.modules.content.account_models import Platform
from app.modules.risk_rag.ingestion import (
    EmbeddingSpec,
    IncompleteEmbeddingRebuild,
    MockRiskEmbedder,
    RiskEmbeddingService,
    RiskIngestionService,
)
from app.modules.risk_rag.models import (
    RiskAuthorizationStatus,
    RiskDocument,
    RiskDocumentScope,
    RiskDocumentStatus,
    RiskChunk,
    RiskChunkEmbedding,
    RiskSourceLevel,
)
from app.modules.risk_rag.repository import RiskDocumentRepository
from app.modules.risk_rag.tasks import (
    process_risk_web_source_task,
    process_web_source,
)
from app.modules.style_facts.fact_tasks import FactHttpResponse
from app.modules.workspace.models import Workspace, WorkspaceMember


class RecordingStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.put_count = 0

    def put_object(
        self,
        object_key: str,
        content: bytes,
        *,
        mime_type: str,
    ) -> None:
        self.put_count += 1
        self.objects[object_key] = (content, mime_type)


class RecordingFetcher:
    def __init__(self, response: FactHttpResponse) -> None:
        self.response = response
        self.targets = []

    def request(self, target):
        self.targets.append(target)
        return self.response


def test_celery_web_ingestion_task_has_bounded_network_retries() -> None:
    assert process_risk_web_source_task.name == (
        "risk_rag.process_web_source"
    )
    assert process_risk_web_source_task.max_retries == 3
    assert process_risk_web_source_task.retry_backoff is True
    assert process_risk_web_source_task.autoretry_for == (
        ConnectionError,
        OSError,
        TimeoutError,
    )


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        yield database_session


def _active_web_document(
    session: Session,
) -> tuple[WorkspaceContext, RiskDocument]:
    workspace = Workspace(name="合成网页版本工作区")
    reviewer = WorkspaceMember(
        workspace_id=workspace.id,
        display_name="合成网页审核员",
        role="admin",
    )
    session.add_all([workspace, reviewer])
    session.flush()
    document = RiskDocument(
        workspace_id=workspace.id,
        platform=Platform.XIAOHONGSHU,
        scope=RiskDocumentScope.PRIVATE,
        source_level=RiskSourceLevel.S3,
        title="人工合成网页规则",
        source_url="https://risk.example.invalid/synthetic",
        authorization_status=RiskAuthorizationStatus.AUTHORIZED,
        status=RiskDocumentStatus.ACTIVE,
        version=1,
        effective_at=datetime(2026, 7, 20, 8, tzinfo=UTC),
        reviewed_by=reviewer.id,
        content_sha256="0" * 64,
        object_key=(
            f"workspaces/{workspace.id}/risk-knowledge/"
            "synthetic-old-version"
        ),
        resolved_ips=["93.184.216.34"],
    )
    session.add(document)
    session.commit()
    return (
        WorkspaceContext(
            workspace_id=workspace.id,
            member_id=reviewer.id,
            role="admin",
        ),
        document,
    )


def test_changed_webpage_creates_pending_review_version_and_keeps_old_active(
    session: Session,
) -> None:
    context, old = _active_web_document(session)
    storage = RecordingStorage()
    accessed_at = datetime(2026, 7, 23, 8, tzinfo=UTC)
    content = (
        "<h1>第一章 人工测试</h1>"
        "<p>第一条 这是变化后的合成网页内容。</p>"
    ).encode()

    pending = RiskIngestionService(
        session,
        context,
        storage=storage,
    ).ingest_web_snapshot(
        old.id,
        content=content,
        mime_type="text/html",
        accessed_at=accessed_at,
        published_at=accessed_at - timedelta(days=1),
        redistribution_authorized=False,
    )
    session.commit()

    assert pending.id != old.id
    assert pending.previous_version_id == old.id
    assert pending.version == 2
    assert pending.status is RiskDocumentStatus.PENDING_REVIEW
    assert pending.reviewed_by is None
    assert pending.accessed_at == accessed_at
    assert pending.object_key in storage.objects
    assert old.status is RiskDocumentStatus.ACTIVE
    repository = RiskDocumentRepository(session, context=context)
    assert repository.list_current(
        platform=Platform.XIAOHONGSHU,
        at=accessed_at,
    ) == [old]
    assert repository.version_chain(pending.id) == [pending, old]


def test_web_task_retry_reuses_pending_version_without_duplicate_upload(
    session: Session,
) -> None:
    context, old = _active_web_document(session)
    storage = RecordingStorage()
    accessed_at = datetime(2026, 7, 23, 9, tzinfo=UTC)
    response = FactHttpResponse(
        status=200,
        headers={"content-type": "text/html"},
        peer_ip="93.184.216.34",
        text="<p>第一条 完全人工生成的网页快照。</p>",
        published_at=None,
    )
    fetcher = RecordingFetcher(response)

    first = process_web_source(
        session,
        context=context,
        document_id=old.id,
        fetcher=fetcher,
        storage=storage,
        accessed_at=accessed_at,
    )
    retried = process_web_source(
        session,
        context=context,
        document_id=old.id,
        fetcher=fetcher,
        storage=storage,
        accessed_at=accessed_at,
    )
    session.commit()

    versions = list(
        session.scalars(
            select(RiskDocument).where(
                RiskDocument.workspace_id == context.workspace_id
            )
        )
    )
    assert retried.id == first.id
    assert len(versions) == 2
    assert storage.put_count == 1
    assert len(fetcher.targets) == 2
    assert fetcher.targets[0].resolved_ips == ("93.184.216.34",)


def test_web_task_rejects_dns_rebind_peer(session: Session) -> None:
    context, old = _active_web_document(session)
    response = FactHttpResponse(
        status=200,
        headers={"content-type": "text/html"},
        peer_ip="127.0.0.1",
        text="<p>不应被接收的人工内容。</p>",
        published_at=None,
    )

    with pytest.raises(ValueError, match="rebind"):
        process_web_source(
            session,
            context=context,
            document_id=old.id,
            fetcher=RecordingFetcher(response),
            storage=RecordingStorage(),
            accessed_at=datetime(2026, 7, 23, 9, tzinfo=UTC),
        )


def _add_chunks(
    session: Session,
    document: RiskDocument,
    *texts: str,
) -> list[RiskChunk]:
    chunks = [
        RiskChunk(
            workspace_id=document.workspace_id,
            document_id=document.id,
            platform=document.platform,
            scope=document.scope,
            chunk_index=index,
            source_location=f"人工条款 {index + 1}",
            text=text,
        )
        for index, text in enumerate(texts)
    ]
    session.add_all(chunks)
    session.commit()
    return chunks


def test_embedding_rows_record_model_dimension_and_version(
    session: Session,
) -> None:
    context, document = _active_web_document(session)
    chunks = _add_chunks(session, document, "合成片段一", "合成片段二")
    service = RiskEmbeddingService(session, context)
    spec = EmbeddingSpec(
        model_id="mock-embedding-v1",
        dimension=3,
        version="2026-07-a",
    )

    rows = service.rebuild(
        platform=Platform.XIAOHONGSHU,
        spec=spec,
        vectors={
            chunks[0].id: [0.1, 0.2, 0.3],
            chunks[1].id: [0.4, 0.5, 0.6],
        },
    )
    session.commit()

    assert {row.model_id for row in rows} == {"mock-embedding-v1"}
    assert {row.dimension for row in rows} == {3}
    assert {row.embedding_version for row in rows} == {"2026-07-a"}
    assert {row.workspace_id for row in rows} == {context.workspace_id}
    assert {row.platform for row in rows} == {Platform.XIAOHONGSHU}


def test_model_change_requires_complete_atomic_rebuild(
    session: Session,
) -> None:
    context, document = _active_web_document(session)
    chunks = _add_chunks(session, document, "合成片段甲", "合成片段乙")
    service = RiskEmbeddingService(session, context)
    old_spec = EmbeddingSpec(
        model_id="mock-old",
        dimension=2,
        version="v1",
    )
    service.rebuild(
        platform=Platform.XIAOHONGSHU,
        spec=old_spec,
        vectors={
            chunks[0].id: [0.1, 0.2],
            chunks[1].id: [0.3, 0.4],
        },
    )
    session.commit()

    new_spec = EmbeddingSpec(
        model_id="mock-new",
        dimension=3,
        version="v2",
    )
    with pytest.raises(IncompleteEmbeddingRebuild, match="all platform chunks"):
        service.rebuild(
            platform=Platform.XIAOHONGSHU,
            spec=new_spec,
            vectors={chunks[0].id: [0.1, 0.2, 0.3]},
        )
    session.rollback()
    assert {
        row.model_id
        for row in session.scalars(select(RiskChunkEmbedding))
    } == {"mock-old"}

    replaced = service.rebuild(
        platform=Platform.XIAOHONGSHU,
        spec=new_spec,
        vectors={
            chunks[0].id: [0.1, 0.2, 0.3],
            chunks[1].id: [0.4, 0.5, 0.6],
        },
    )
    session.commit()

    assert len(replaced) == 2
    all_rows = list(session.scalars(select(RiskChunkEmbedding)))
    assert {
        (row.model_id, row.dimension, row.embedding_version)
        for row in all_rows
        if row.is_active
    } == {("mock-new", 3, "v2")}
    assert {
        (row.model_id, row.dimension, row.embedding_version)
        for row in all_rows
        if not row.is_active
    } == {("mock-old", 2, "v1")}


def test_embedding_dimension_mismatch_is_rejected_without_deleting_index(
    session: Session,
) -> None:
    context, document = _active_web_document(session)
    chunk = _add_chunks(session, document, "合成维度测试片段")[0]
    service = RiskEmbeddingService(session, context)

    with pytest.raises(ValueError, match="dimension"):
        service.rebuild(
            platform=Platform.XIAOHONGSHU,
            spec=EmbeddingSpec(
                model_id="mock-dimension",
                dimension=3,
                version="v1",
            ),
            vectors={chunk.id: [0.1, 0.2]},
        )

    assert list(session.scalars(select(RiskChunkEmbedding))) == []


def test_mock_embedding_contract_is_deterministic_and_rebuilds_without_network(
    session: Session,
) -> None:
    context, document = _active_web_document(session)
    chunks = _add_chunks(session, document, "合成向量文本一", "合成向量文本二")
    embedder = MockRiskEmbedder()
    service = RiskEmbeddingService(session, context)

    first = service.rebuild_with(
        platform=Platform.XIAOHONGSHU,
        embedder=embedder,
        embedding_version="mock-contract-v1",
    )
    first_vectors = [list(row.vector) for row in first]
    session.commit()
    second = service.rebuild_with(
        platform=Platform.XIAOHONGSHU,
        embedder=embedder,
        embedding_version="mock-contract-v1",
    )

    assert embedder.model_id == "mock-v1"
    assert embedder.dimension == 4
    assert [list(row.vector) for row in second] == first_vectors
    assert first_vectors[0] != first_vectors[1]
    assert {row.chunk_id for row in second} == {chunk.id for chunk in chunks}
