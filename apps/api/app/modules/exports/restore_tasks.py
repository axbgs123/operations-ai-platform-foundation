from uuid import UUID

from celery import shared_task

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.core.logging import current_request_id, task_request_context
from app.core.observability import record_task_correlation
from app.core.storage import get_storage
from sqlalchemy import select

from app.modules.exports.models import (
    KnowledgeIndexRebuild,
    KnowledgeIndexStatus,
    RestoreJob,
)
from app.modules.risk_rag.index_tasks import enqueue_risk_index_rebuild
from app.modules.exports.zip_restore import process_full_restore_task


def enqueue_restore(task_id: UUID) -> None:
    request_id = current_request_id()
    if get_settings().app_mock_mode:
        restore_workspace_task(str(task_id), request_id)
    else:
        restore_workspace_task.delay(str(task_id), request_id)


def get_restore_enqueuer():
    return enqueue_restore


@shared_task(name="exports.restore_workspace")
def restore_workspace_task(task_id: str, request_id: str | None = None) -> None:
    with task_request_context(request_id) as safe_request_id:
        with SessionFactory() as session:
            parsed_id = UUID(task_id)
            job = session.get(RestoreJob, parsed_id)
            if job is not None:
                record_task_correlation(
                    session,
                    workspace_id=job.workspace_id,
                    task_id=job.id,
                    task_type="restore",
                    request_id=safe_request_id,
                )
                session.commit()
            process_full_restore_task(
                session,
                parsed_id,
                get_storage(),
            )
            queued = list(
                session.scalars(
                    select(KnowledgeIndexRebuild.id).where(
                        KnowledgeIndexRebuild.restore_job_id == parsed_id,
                        KnowledgeIndexRebuild.status
                        == KnowledgeIndexStatus.QUEUED,
                    )
                )
            )
        for rebuild_id in queued:
            enqueue_risk_index_rebuild(rebuild_id)
