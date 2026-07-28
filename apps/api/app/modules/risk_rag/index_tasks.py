from __future__ import annotations

from uuid import UUID

from celery import shared_task
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.modules.exports.models import (
    KnowledgeIndexRebuild,
    KnowledgeIndexStatus,
    RestoreJob,
)
from app.modules.models.adapters.qianwen_embedding import QianwenRiskEmbedder
from app.modules.models.catalog import QianwenRegion
from app.modules.models.config_service import SecretCipher
from app.modules.models.models import ModelConfig
from app.modules.risk_rag.indexing import (
    ConfiguredMockRiskEmbedder,
    RiskIndexRebuildCoordinator,
)
from app.core.security import WorkspaceContext


def _load_embedder(session: Session, job_id: UUID):
    job = session.get(KnowledgeIndexRebuild, job_id)
    if job is None or job.model_config_id is None:
        raise LookupError("knowledge index rebuild not found")
    config = session.get(ModelConfig, job.model_config_id)
    if config is None or config.workspace_id != job.workspace_id:
        raise LookupError("embedding model config not found")
    if config.provider == "mock":
        return (
            job.workspace_id,
            ConfiguredMockRiskEmbedder(config.id, config.model_id),
        )
    if (
        config.provider != "qianwen"
        or config.region is None
        or config.provider_workspace_id is None
    ):
        raise ValueError("embedding model config is unsupported")
    cipher = SecretCipher(
        get_settings().model_secret_encryption_key.get_secret_value()
    )
    if config.encryption_key_version != cipher.version:
        raise ValueError("embedding model key version is unsupported")
    return (
        job.workspace_id,
        QianwenRiskEmbedder(
            workspace_id=job.workspace_id,
            model_config_id=config.id,
            region=QianwenRegion(config.region),
            provider_workspace_id=config.provider_workspace_id,
            api_key=SecretStr(cipher.decrypt(config.encrypted_api_key)),
            model_id=config.model_id,
            contract_version=job.contract_version or "",
            dimension=job.dimension or 0,
        ),
    )


def enqueue_risk_index_rebuild(job_id: UUID) -> None:
    settings = get_settings()
    if settings.app_mock_mode:
        # Mock CI may execute deterministic local builds inline. A Qianwen job
        # remains durably queued so ordinary tests can never make a paid call.
        with SessionFactory() as session:
            job = session.get(KnowledgeIndexRebuild, job_id)
            if job is None or job.provider != "mock":
                return
        rebuild_risk_index_task(str(job_id))
        return
    rebuild_risk_index_task.delay(str(job_id))


@shared_task(name="risk_rag.rebuild_index")
def rebuild_risk_index_task(job_id: str) -> None:
    parsed_id = UUID(job_id)
    with SessionFactory() as session:
        workspace_id, embedder = _load_embedder(session, parsed_id)
    context = WorkspaceContext(
        workspace_id=workspace_id,
        member_id=UUID(int=0),
        role="admin",
    )
    try:
        RiskIndexRebuildCoordinator(
            SessionFactory, context=context
        ).run(parsed_id, embedder=embedder)
    finally:
        _sync_restore_index_message(parsed_id)


def _sync_restore_index_message(job_id: UUID) -> None:
    with SessionFactory() as session, session.begin():
        rebuild = session.get(KnowledgeIndexRebuild, job_id)
        if rebuild is None or rebuild.restore_job_id is None:
            return
        restore = session.get(RestoreJob, rebuild.restore_job_id)
        if restore is None:
            return
        statuses = set(
            session.scalars(
                select(KnowledgeIndexRebuild.status).where(
                    KnowledgeIndexRebuild.restore_job_id == restore.id
                )
            )
        )
        if statuses and statuses <= {KnowledgeIndexStatus.SUCCEEDED}:
            restore.knowledge_index_message = None
        elif KnowledgeIndexStatus.FAILED in statuses:
            restore.knowledge_index_message = "知识索引重建失败"
        else:
            restore.knowledge_index_message = "知识索引重建中"
