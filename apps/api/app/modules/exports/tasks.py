from uuid import UUID

from celery import shared_task

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.core.logging import current_request_id, task_request_context
from app.core.observability import record_task_correlation
from app.modules.exports.models import ExportTask
from app.core.storage import get_storage
from app.modules.exports.service import (
    mark_export_enqueued,
    process_export_task,
    recoverable_export_task_ids,
)


def enqueue_export(task_id: UUID) -> None:
    request_id = current_request_id()
    if get_settings().run_tasks_inline:
        generate_export_task(str(task_id), request_id)
    else:
        generate_export_task.delay(str(task_id), request_id)


def get_export_enqueuer():
    return enqueue_export


@shared_task(name="exports.generate")
def generate_export_task(task_id: str, request_id: str | None = None) -> None:
    with task_request_context(request_id) as safe_request_id:
        with SessionFactory() as session:
            parsed_id = UUID(task_id)
            task = session.get(ExportTask, parsed_id)
            if task is not None:
                record_task_correlation(
                    session,
                    workspace_id=task.workspace_id,
                    task_id=task.id,
                    task_type="export",
                    request_id=safe_request_id,
                )
                session.commit()
            process_export_task(session, parsed_id, get_storage())
            session.commit()


@shared_task(name="exports.recover_pending")
def recover_pending_export_tasks() -> None:
    with SessionFactory() as session:
        task_ids = recoverable_export_task_ids(session)
        for task_id in task_ids:
            try:
                generate_export_task.delay(str(task_id), current_request_id())
            except Exception:
                continue
            mark_export_enqueued(session, task_id)
        session.commit()
