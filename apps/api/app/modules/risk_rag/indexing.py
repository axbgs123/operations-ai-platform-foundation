from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import math
import secrets
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.content.account_models import Platform
from app.modules.exports.models import (
    KnowledgeIndexRebuild,
    KnowledgeIndexStatus,
)
from app.modules.models.capabilities import Capability
from app.modules.models.catalog import get_catalog_entry
from app.modules.models.models import ModelConfig, ModelConfigStatus
from app.modules.models.config_service import model_configuration_version
from app.modules.risk_rag.models import (
    RiskAuthorizationStatus,
    RiskChunk,
    RiskChunkEmbedding,
    RiskDocument,
    RiskDocumentScope,
    RiskDocumentStatus,
)
from app.modules.risk_rag.ingestion import MockRiskEmbedder
from app.modules.workspace.permissions import Permission, require_permission


class BatchRiskEmbedder(Protocol):
    model_config_id: UUID
    model_id: str
    contract_version: str
    dimension: int

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]: ...


class IndexBuildFailed(RuntimeError):
    pass


class ConfiguredMockRiskEmbedder:
    contract_version = "mock-risk-embedding-v1"
    dimension = 4

    def __init__(self, model_config_id: UUID, model_id: str = "mock-v1") -> None:
        self.model_config_id = model_config_id
        self.model_id = model_id
        self._delegate = MockRiskEmbedder()

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._delegate.embed(text) for text in texts]


@dataclass(frozen=True)
class _FrozenChunk:
    id: UUID
    workspace_id: UUID
    platform: Platform
    scope: RiskDocumentScope
    text: str
    fingerprint: str


SessionFactory = Callable[[], Session]
Clock = Callable[[], datetime]
PublishHook = Callable[[], None]


class RiskIndexRebuildCoordinator:
    """Blue-green index rebuild with short database transactions.

    Provider calls happen only after the snapshot transaction and its Session
    have closed. A claim token fences stale workers; staged rows are inactive
    until one transaction validates and switches the active generation.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        context: WorkspaceContext,
        clock: Clock = lambda: datetime.now(UTC),
        publish_hook: PublishHook | None = None,
        lease_seconds: int = 600,
    ) -> None:
        self._session_factory = session_factory
        self._context = context
        self._clock = clock
        self._publish_hook = publish_hook
        self._lease_seconds = lease_seconds

    def request(
        self,
        *,
        platform: Platform,
        model_config_id: UUID,
        idempotency_key: str,
        restore_job_id: UUID | None = None,
    ) -> UUID:
        require_permission(
            self._context.role, Permission.MANAGE_RISK_KNOWLEDGE
        )
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise ValueError("invalid index rebuild idempotency key")
        with self._session_factory() as session, session.begin():
            existing = session.scalar(
                select(KnowledgeIndexRebuild).where(
                    KnowledgeIndexRebuild.workspace_id
                    == self._context.workspace_id,
                    KnowledgeIndexRebuild.platform == platform,
                    KnowledgeIndexRebuild.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                if existing.model_config_id != model_config_id:
                    raise ValueError("index rebuild idempotency conflict")
                return existing.id
            config = self._config(session, model_config_id)
            entry = get_catalog_entry(config.provider, config.model_id)
            if Capability.EMBEDDING not in entry.capabilities:
                raise ValueError("model config does not provide embedding")

            # A newer request invalidates only unfinished workers. A successful
            # active generation remains available until the new publish.
            session.execute(
                update(KnowledgeIndexRebuild)
                .where(
                    KnowledgeIndexRebuild.workspace_id
                    == self._context.workspace_id,
                    KnowledgeIndexRebuild.platform == platform,
                    KnowledgeIndexRebuild.status.in_(
                        (
                            KnowledgeIndexStatus.QUEUED,
                            KnowledgeIndexStatus.RUNNING,
                        )
                    ),
                )
                .values(
                    status=KnowledgeIndexStatus.FAILED,
                    error_code="INDEX_REBUILD_SUPERSEDED",
                    claim_token=None,
                    lease_expires_at=None,
                )
            )
            config_version = model_configuration_version(config)
            job = KnowledgeIndexRebuild(
                workspace_id=self._context.workspace_id,
                platform=platform,
                status=KnowledgeIndexStatus.QUEUED,
                index_generation=secrets.token_hex(16),
                idempotency_key=idempotency_key,
                restore_job_id=restore_job_id,
                model_id=config.model_id,
                model_config_id=config.id,
                provider=config.provider,
                region=config.region,
                contract_version=entry.contract_version,
                config_version=config_version,
                embedding_version=entry.contract_version,
                dimension=entry.embedding_dimension,
            )
            session.add(job)
            session.flush()
            # Use the durable UUID as the externally compared generation.
            job.index_generation = str(job.id)
            return job.id

    def run(
        self,
        job_id: UUID,
        *,
        embedder: BatchRiskEmbedder,
    ) -> None:
        claim_token = secrets.token_hex(24)
        try:
            frozen, expected = self._claim_and_snapshot(
                job_id, claim_token=claim_token, embedder=embedder
            )
            vectors: dict[UUID, list[float]] = {}
            if expected.dimension is None:
                raise IndexBuildFailed("embedding dimension is not frozen")
            for offset in range(0, len(frozen), 10):
                batch = frozen[offset : offset + 10]
                result = embedder.embed_batch([item.text for item in batch])
                if len(result) != len(batch):
                    raise IndexBuildFailed(
                        "embedding batch count does not match input"
                    )
                for item, vector in zip(batch, result, strict=True):
                    self._validate_vector(vector, expected.dimension)
                    vectors[item.id] = list(vector)
            self._stage_and_publish(
                job_id,
                claim_token=claim_token,
                expected=expected,
                frozen=frozen,
                vectors=vectors,
            )
        except IndexBuildFailed:
            self._mark_failed(job_id, claim_token)
            raise
        except Exception as error:
            self._mark_failed(job_id, claim_token)
            raise IndexBuildFailed("index rebuild failed") from error

    def _claim_and_snapshot(
        self,
        job_id: UUID,
        *,
        claim_token: str,
        embedder: BatchRiskEmbedder,
    ) -> tuple[list[_FrozenChunk], KnowledgeIndexRebuild]:
        now = self._aware_now()
        with self._session_factory() as session, session.begin():
            job = self._owned_job(session, job_id)
            if job.status is not KnowledgeIndexStatus.QUEUED:
                raise IndexBuildFailed("index rebuild claim is not current")
            if (
                job.model_config_id != embedder.model_config_id
                or job.model_id != embedder.model_id
                or job.contract_version != embedder.contract_version
                or job.dimension != embedder.dimension
            ):
                raise IndexBuildFailed("embedder does not match frozen config")
            job.status = KnowledgeIndexStatus.RUNNING
            job.claim_token = claim_token
            job.lease_expires_at = now + timedelta(
                seconds=self._lease_seconds
            )
            job.attempt_count += 1
            frozen = self._eligible_chunks(session, job)
            job.total_chunks = len(frozen)
            job.chunk_manifest_digest = self._manifest_digest(frozen)
            session.flush()
            session.expunge(job)
            return frozen, job

    def _stage_and_publish(
        self,
        job_id: UUID,
        *,
        claim_token: str,
        expected: KnowledgeIndexRebuild,
        frozen: list[_FrozenChunk],
        vectors: dict[UUID, list[float]],
    ) -> None:
        now = self._aware_now()
        if set(vectors) != {item.id for item in frozen}:
            raise IndexBuildFailed("index rebuild is incomplete")
        with self._session_factory() as session, session.begin():
            job = self._owned_job(session, job_id)
            self._validate_claim(job, claim_token, now)
            if not self._same_contract(job, expected):
                raise IndexBuildFailed("index rebuild config changed")
            config = self._config(session, job.model_config_id)
            if model_configuration_version(config) != job.config_version:
                raise IndexBuildFailed("index rebuild config changed")
            current = self._eligible_chunks(session, job)
            if self._manifest_digest(current) != job.chunk_manifest_digest:
                raise IndexBuildFailed("risk chunk set changed during rebuild")
            by_id = {item.id: item for item in current}
            session.add_all(
                [
                    RiskChunkEmbedding(
                        workspace_id=item.workspace_id,
                        chunk_id=item.id,
                        platform=item.platform,
                        scope=item.scope,
                        model_id=job.model_id or "",
                        dimension=job.dimension or 0,
                        embedding_version=job.embedding_version or "",
                        vector=vectors[item.id],
                        provider=job.provider or "",
                        model_config_id=job.model_config_id,
                        contract_version=job.contract_version or "",
                        config_version=job.config_version or "",
                        index_generation=job.index_generation,
                        is_active=False,
                    )
                    for item in current
                ]
            )
            session.flush()
            staged = list(
                session.scalars(
                    select(RiskChunkEmbedding).where(
                        RiskChunkEmbedding.workspace_id == job.workspace_id,
                        RiskChunkEmbedding.platform == job.platform,
                        RiskChunkEmbedding.index_generation
                        == job.index_generation,
                    )
                )
            )
            if len(staged) != len(by_id) or {
                row.chunk_id for row in staged
            } != set(by_id):
                raise IndexBuildFailed("staged index validation failed")

            session.execute(
                update(RiskChunkEmbedding)
                .where(
                    RiskChunkEmbedding.workspace_id == job.workspace_id,
                    RiskChunkEmbedding.platform == job.platform,
                    RiskChunkEmbedding.is_active.is_(True),
                )
                .values(is_active=False)
            )
            session.execute(
                update(KnowledgeIndexRebuild)
                .where(
                    KnowledgeIndexRebuild.workspace_id == job.workspace_id,
                    KnowledgeIndexRebuild.platform == job.platform,
                    KnowledgeIndexRebuild.is_active.is_(True),
                    KnowledgeIndexRebuild.id != job.id,
                )
                .values(is_active=False)
            )
            for row in staged:
                row.is_active = True
            job.status = KnowledgeIndexStatus.SUCCEEDED
            job.completed_chunks = len(staged)
            job.is_active = True
            job.activated_at = now
            job.claim_token = None
            job.lease_expires_at = None
            job.error_code = None
            if self._publish_hook is not None:
                self._publish_hook()

    def _mark_failed(self, job_id: UUID, claim_token: str) -> None:
        with self._session_factory() as session, session.begin():
            job = session.scalar(
                select(KnowledgeIndexRebuild).where(
                    KnowledgeIndexRebuild.id == job_id,
                    KnowledgeIndexRebuild.workspace_id
                    == self._context.workspace_id,
                )
            )
            if (
                job is None
                or job.status is not KnowledgeIndexStatus.RUNNING
                or job.claim_token != claim_token
            ):
                return
            session.execute(
                delete(RiskChunkEmbedding).where(
                    RiskChunkEmbedding.workspace_id == job.workspace_id,
                    RiskChunkEmbedding.platform == job.platform,
                    RiskChunkEmbedding.index_generation
                    == job.index_generation,
                    RiskChunkEmbedding.is_active.is_(False),
                )
            )
            job.status = KnowledgeIndexStatus.FAILED
            job.error_code = "KNOWLEDGE_INDEX_REBUILD_FAILED"
            job.claim_token = None
            job.lease_expires_at = None

    def _eligible_chunks(
        self, session: Session, job: KnowledgeIndexRebuild
    ) -> list[_FrozenChunk]:
        if job.provider == "qianwen":
            scope_filter = (
                RiskDocument.scope == RiskDocumentScope.PRIVATE,
                RiskDocument.workspace_id == job.workspace_id,
                RiskChunk.scope == RiskDocumentScope.PRIVATE,
                RiskChunk.workspace_id == job.workspace_id,
            )
        else:
            # Workspace rebuilds never spend a private key on global public
            # knowledge. Public indexes remain separately governed/prebuilt.
            scope_filter = (
                RiskDocument.scope == RiskDocumentScope.PRIVATE,
                RiskDocument.workspace_id == job.workspace_id,
                RiskChunk.scope == RiskDocumentScope.PRIVATE,
                RiskChunk.workspace_id == job.workspace_id,
            )
        rows = session.execute(
            select(RiskChunk, RiskDocument)
            .join(RiskDocument, RiskDocument.id == RiskChunk.document_id)
            .where(
                *scope_filter,
                RiskDocument.platform == job.platform,
                RiskChunk.platform == job.platform,
                RiskDocument.status == RiskDocumentStatus.ACTIVE,
                RiskDocument.effective_at.is_not(None),
                RiskDocument.effective_at <= self._aware_now(),
                RiskDocument.authorization_status
                != RiskAuthorizationStatus.RESTRICTED,
            )
            .order_by(
                RiskDocument.id, RiskDocument.version, RiskChunk.chunk_index
            )
        )
        result: list[_FrozenChunk] = []
        for chunk, document in rows:
            fingerprint = hashlib.sha256(
                (
                    f"{chunk.id}:{document.id}:{document.version}:"
                    f"{document.status.value}:{chunk.chunk_index}:"
                ).encode()
                + chunk.text.encode("utf-8")
            ).hexdigest()
            result.append(
                _FrozenChunk(
                    id=chunk.id,
                    workspace_id=job.workspace_id,
                    platform=job.platform,
                    scope=chunk.scope,
                    text=chunk.text,
                    fingerprint=fingerprint,
                )
            )
        return result

    def _config(self, session: Session, config_id: UUID | None) -> ModelConfig:
        if config_id is None:
            raise IndexBuildFailed("embedding configuration is required")
        config = session.scalar(
            select(ModelConfig).where(
                ModelConfig.id == config_id,
                ModelConfig.workspace_id == self._context.workspace_id,
                ModelConfig.status != ModelConfigStatus.INCOMPATIBLE,
            )
        )
        if config is None:
            raise LookupError("model config not found")
        return config

    @staticmethod
    def _manifest_digest(chunks: list[_FrozenChunk]) -> str:
        return hashlib.sha256(
            "\n".join(
                f"{item.id}:{item.fingerprint}" for item in chunks
            ).encode()
        ).hexdigest()

    @staticmethod
    def _validate_vector(vector: list[float], dimension: int) -> None:
        if len(vector) != dimension:
            raise IndexBuildFailed("embedding vector dimension mismatch")
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            for value in vector
        ):
            raise IndexBuildFailed("embedding vector is invalid")
        if math.isclose(sum(float(value) ** 2 for value in vector), 0.0):
            raise IndexBuildFailed("embedding vector is zero")

    def _owned_job(
        self, session: Session, job_id: UUID
    ) -> KnowledgeIndexRebuild:
        job = session.scalar(
            select(KnowledgeIndexRebuild).where(
                KnowledgeIndexRebuild.id == job_id,
                KnowledgeIndexRebuild.workspace_id
                == self._context.workspace_id,
            )
        )
        if job is None:
            raise LookupError("knowledge index rebuild not found")
        return job

    @staticmethod
    def _same_contract(
        current: KnowledgeIndexRebuild, expected: KnowledgeIndexRebuild
    ) -> bool:
        return (
            current.model_config_id,
            current.provider,
            current.model_id,
            current.region,
            current.contract_version,
            current.config_version,
            current.dimension,
            current.index_generation,
            current.operation_version,
        ) == (
            expected.model_config_id,
            expected.provider,
            expected.model_id,
            expected.region,
            expected.contract_version,
            expected.config_version,
            expected.dimension,
            expected.index_generation,
            expected.operation_version,
        )

    @staticmethod
    def _validate_claim(
        job: KnowledgeIndexRebuild, claim_token: str, now: datetime
    ) -> None:
        if (
            job.status is not KnowledgeIndexStatus.RUNNING
            or job.claim_token != claim_token
            or job.lease_expires_at is None
            or job.lease_expires_at < now
        ):
            raise IndexBuildFailed("index rebuild claim is no longer current")

    def _aware_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("index rebuild clock must be timezone-aware")
        return now
