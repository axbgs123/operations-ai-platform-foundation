from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Load the complete application metadata before create_all, matching Alembic.
from app.core import observability as observability_models  # noqa: F401
from app.core.database import Base
from app.core.security import WorkspaceContext
from app.modules.analysis import models as analysis_models  # noqa: F401
from app.modules.analysis import viral_models  # noqa: F401
from app.modules.content import models as content_models  # noqa: F401
from app.modules.content.account_models import Platform
from app.modules.generation import models as generation_models  # noqa: F401
from app.modules.imports import capture_models, models as import_models  # noqa: F401
from app.modules.metrics import models as metric_models  # noqa: F401
from app.modules.exports.models import (
    KnowledgeIndexRebuild,
    KnowledgeIndexStatus,
)
from app.modules.models.catalog import (
    QIANWEN_EMBEDDING_CONTRACT_VERSION,
    QIANWEN_EMBEDDING_DIMENSION,
    QIANWEN_EMBEDDING_MODEL_ID,
)
from app.modules.models.models import ModelConfig, ModelConfigStatus
from app.modules.risk_rag.indexing import (
    IndexBuildFailed,
    RiskIndexRebuildCoordinator,
)
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
    ActiveRiskIndexUnavailable,
    resolve_active_retrieval_filter,
    retrieve_with_active_index,
)
from app.modules.style_facts import fact_models, style_models  # noqa: F401
from app.modules.workspace.models import Workspace
from app.modules.workspace.permissions import PermissionDenied


NOW = datetime(2026, 7, 28, 12, tzinfo=UTC)


class FixedEmbedder:
    model_id = QIANWEN_EMBEDDING_MODEL_ID
    contract_version = QIANWEN_EMBEDDING_CONTRACT_VERSION
    dimension = QIANWEN_EMBEDDING_DIMENSION

    def __init__(self, model_config_id: UUID) -> None:
        self.model_config_id = model_config_id
        self.calls: list[tuple[str, ...]] = []
        self.during_call = None

    def embed_batch(self, texts) -> list[list[float]]:
        self.calls.append(tuple(texts))
        if self.during_call is not None:
            self.during_call()
        return [
            [float(index + 1)]
            + [0.001] * (QIANWEN_EMBEDDING_DIMENSION - 1)
            for index, _ in enumerate(texts)
        ]


@pytest.fixture
def database():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def _seed(factory) -> tuple[WorkspaceContext, ModelConfig]:
    with factory.begin() as session:
        workspace = Workspace(name="synthetic-risk-workspace")
        session.add(workspace)
        session.flush()
        config = ModelConfig(
            workspace_id=workspace.id,
            provider="qianwen",
            model_id=QIANWEN_EMBEDDING_MODEL_ID,
            capabilities=["embedding"],
            status=ModelConfigStatus.EXPERIMENTAL,
            encrypted_api_key="encrypted-synthetic",
            region="cn-beijing",
            provider_workspace_id="llm-abcd1234",
            encryption_key_version="v1",
        )
        session.add(config)
        document = RiskDocument(
            workspace_id=workspace.id,
            platform=Platform.DOUYIN,
            scope=RiskDocumentScope.PRIVATE,
            source_level=RiskSourceLevel.S3,
            title="人工合成风控资料",
            private_document_id="synthetic-private-knowledge",
            authorization_status=RiskAuthorizationStatus.AUTHORIZED,
            status=RiskDocumentStatus.ACTIVE,
            version=1,
            effective_at=NOW - timedelta(days=1),
        )
        session.add(document)
        session.flush()
        session.add_all(
            [
                RiskChunk(
                    workspace_id=workspace.id,
                    document_id=document.id,
                    platform=Platform.DOUYIN,
                    scope=RiskDocumentScope.PRIVATE,
                    chunk_index=index,
                    source_location=f"人工片段 {index + 1}",
                    text=text,
                    metadata_json={"untrusted_data": True},
                )
                for index, text in enumerate(("合成资料甲", "合成资料乙"))
            ]
        )
        context = WorkspaceContext(
            workspace_id=workspace.id,
            member_id=uuid4(),
            role="admin",
        )
    return context, config


def _coordinator(factory, context, *, publish_hook=None):
    return RiskIndexRebuildCoordinator(
        factory,
        context=context,
        clock=lambda: NOW,
        publish_hook=publish_hook,
    )


def test_provider_calls_run_after_database_session_is_released(database) -> None:
    context, config = _seed(database)
    coordinator = _coordinator(database, context)
    job_id = coordinator.request(
        platform=Platform.DOUYIN,
        model_config_id=config.id,
        idempotency_key="first-build",
    )
    embedder = FixedEmbedder(config.id)

    def assert_no_checked_out_connection() -> None:
        # A separate Session can observe the committed claim while the
        # provider callback runs; the snapshot transaction is no longer open.
        with database() as observer:
            job = observer.get(KnowledgeIndexRebuild, job_id)
            assert job is not None
            assert job.status is KnowledgeIndexStatus.RUNNING
            assert job.claim_token is not None

    embedder.during_call = assert_no_checked_out_connection
    coordinator.run(job_id, embedder=embedder)

    assert len(embedder.calls) == 1


def test_new_generation_is_published_atomically_and_old_is_retained(database) -> None:
    context, config = _seed(database)
    coordinator = _coordinator(database, context)
    first_id = coordinator.request(
        platform=Platform.DOUYIN,
        model_config_id=config.id,
        idempotency_key="first-build",
    )
    coordinator.run(first_id, embedder=FixedEmbedder(config.id))
    second_id = coordinator.request(
        platform=Platform.DOUYIN,
        model_config_id=config.id,
        idempotency_key="second-build",
    )

    with database() as session:
        assert session.get(KnowledgeIndexRebuild, first_id).is_active is True
        assert {
            row.index_generation
            for row in session.scalars(
                select(RiskChunkEmbedding).where(
                    RiskChunkEmbedding.is_active.is_(True)
                )
            )
        } == {str(first_id)}

    coordinator.run(second_id, embedder=FixedEmbedder(config.id))

    with database() as session:
        rows = list(session.scalars(select(RiskChunkEmbedding)))
        assert {row.index_generation for row in rows} == {
            str(first_id),
            str(second_id),
        }
        assert {
            row.index_generation for row in rows if row.is_active
        } == {str(second_id)}
        assert session.get(KnowledgeIndexRebuild, first_id).is_active is False
        assert session.get(KnowledgeIndexRebuild, second_id).is_active is True


def test_failed_build_and_failed_publish_leave_old_index_active(database) -> None:
    context, config = _seed(database)
    coordinator = _coordinator(database, context)
    old_id = coordinator.request(
        platform=Platform.DOUYIN,
        model_config_id=config.id,
        idempotency_key="old-build",
    )
    coordinator.run(old_id, embedder=FixedEmbedder(config.id))

    class BadEmbedder(FixedEmbedder):
        def embed_batch(self, texts):
            return [[1.0, 2.0] for _ in texts]

    failed_id = coordinator.request(
        platform=Platform.DOUYIN,
        model_config_id=config.id,
        idempotency_key="bad-vector-build",
    )
    with pytest.raises(IndexBuildFailed):
        coordinator.run(failed_id, embedder=BadEmbedder(config.id))

    publish_id = coordinator.request(
        platform=Platform.DOUYIN,
        model_config_id=config.id,
        idempotency_key="failed-publish",
    )
    broken = _coordinator(
        database,
        context,
        publish_hook=lambda: (_ for _ in ()).throw(RuntimeError("injected")),
    )
    with pytest.raises(IndexBuildFailed):
        broken.run(publish_id, embedder=FixedEmbedder(config.id))

    with database() as session:
        assert session.get(KnowledgeIndexRebuild, old_id).is_active is True
        assert {
            row.index_generation
            for row in session.scalars(
                select(RiskChunkEmbedding).where(
                    RiskChunkEmbedding.is_active.is_(True)
                )
            )
        } == {str(old_id)}


def test_newer_request_fences_old_worker_from_publish(database) -> None:
    context, config = _seed(database)
    coordinator = _coordinator(database, context)
    old_id = coordinator.request(
        platform=Platform.DOUYIN,
        model_config_id=config.id,
        idempotency_key="old-worker",
    )
    embedder = FixedEmbedder(config.id)

    def supersede_old_worker() -> None:
        coordinator.request(
            platform=Platform.DOUYIN,
            model_config_id=config.id,
            idempotency_key="new-worker",
        )

    embedder.during_call = supersede_old_worker
    with pytest.raises(IndexBuildFailed, match="claim"):
        coordinator.run(old_id, embedder=embedder)

    with database() as session:
        assert session.get(KnowledgeIndexRebuild, old_id).is_active is False
        assert list(
            session.scalars(
                select(RiskChunkEmbedding).where(
                    RiskChunkEmbedding.index_generation == str(old_id)
                )
            )
        ) == []


def test_server_resolves_active_generation_and_client_cannot_select_old(database) -> None:
    context, config = _seed(database)
    coordinator = _coordinator(database, context)
    old_id = coordinator.request(
        platform=Platform.DOUYIN,
        model_config_id=config.id,
        idempotency_key="generation-old",
    )
    coordinator.run(old_id, embedder=FixedEmbedder(config.id))
    new_id = coordinator.request(
        platform=Platform.DOUYIN,
        model_config_id=config.id,
        idempotency_key="generation-current",
    )
    coordinator.run(new_id, embedder=FixedEmbedder(config.id))

    with database() as session:
        resolved = resolve_active_retrieval_filter(
            session,
            workspace_id=context.workspace_id,
            platform=Platform.DOUYIN,
            as_of=NOW,
        )

    assert resolved.index_generation == str(new_id)
    assert resolved.model_config_id == config.id
    assert resolved.embedding_model_id == QIANWEN_EMBEDDING_MODEL_ID
    assert resolved.embedding_version == QIANWEN_EMBEDDING_CONTRACT_VERSION
    assert resolved.embedding_dimension == QIANWEN_EMBEDDING_DIMENSION


def test_rebuild_requires_admin_and_hides_other_workspace_config(database) -> None:
    context, config = _seed(database)
    viewer = WorkspaceContext(
        workspace_id=context.workspace_id,
        member_id=uuid4(),
        role="viewer",
    )
    with pytest.raises(PermissionDenied):
        _coordinator(database, viewer).request(
            platform=Platform.DOUYIN,
            model_config_id=config.id,
            idempotency_key="viewer-forbidden",
        )

    with database.begin() as session:
        other = Workspace(name="other-synthetic-workspace")
        session.add(other)
        session.flush()
        other_config = ModelConfig(
            workspace_id=other.id,
            provider="qianwen",
            model_id=QIANWEN_EMBEDDING_MODEL_ID,
            capabilities=["embedding"],
            status=ModelConfigStatus.EXPERIMENTAL,
            encrypted_api_key="encrypted-other",
            region="cn-beijing",
            provider_workspace_id="llm-other1234",
            encryption_key_version="v1",
        )
        session.add(other_config)
        session.flush()
        other_config_id = other_config.id

    with pytest.raises(LookupError, match="not found"):
        _coordinator(database, context).request(
            platform=Platform.DOUYIN,
            model_config_id=other_config_id,
            idempotency_key="cross-workspace-hidden",
        )


def test_query_embedding_must_match_server_resolved_active_index(database) -> None:
    context, config = _seed(database)
    coordinator = _coordinator(database, context)
    job_id = coordinator.request(
        platform=Platform.DOUYIN,
        model_config_id=config.id,
        idempotency_key="query-binding",
    )
    coordinator.run(job_id, embedder=FixedEmbedder(config.id))

    wrong = FixedEmbedder(uuid4())
    with database() as session, pytest.raises(
        ActiveRiskIndexUnavailable,
        match="MODEL_CONFIGURATION_REQUIRED",
    ):
        retrieve_with_active_index(
            session,
            workspace_id=context.workspace_id,
            platform=Platform.DOUYIN,
            as_of=NOW,
            query_text="人工合成查询",
            embedder=wrong,
            top_k=2,
        )

    with database() as session:
        bundle = retrieve_with_active_index(
            session,
            workspace_id=context.workspace_id,
            platform=Platform.DOUYIN,
            as_of=NOW,
            query_text="人工合成查询",
            embedder=FixedEmbedder(config.id),
            top_k=2,
        )
    assert bundle.evidence
    assert {
        item.workspace_id for item in bundle.evidence
    } == {context.workspace_id}
    assert {
        item.platform for item in bundle.evidence
    } == {Platform.DOUYIN}


def test_active_index_is_rejected_after_model_configuration_changes(database) -> None:
    context, config = _seed(database)
    coordinator = _coordinator(database, context)
    job_id = coordinator.request(
        platform=Platform.DOUYIN,
        model_config_id=config.id,
        idempotency_key="config-change",
    )
    coordinator.run(job_id, embedder=FixedEmbedder(config.id))

    with database.begin() as session:
        current = session.get(ModelConfig, config.id)
        assert current is not None
        current.provider_workspace_id = "llm-changed1234"

    with database() as session, pytest.raises(
        ActiveRiskIndexUnavailable,
        match="MODEL_CONFIGURATION_REQUIRED",
    ):
        resolve_active_retrieval_filter(
            session,
            workspace_id=context.workspace_id,
            platform=Platform.DOUYIN,
            as_of=NOW,
        )
