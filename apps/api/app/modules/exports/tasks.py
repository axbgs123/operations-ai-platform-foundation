from uuid import UUID

from celery import shared_task

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.core.storage import get_storage
from app.modules.exports.service import (
    mark_export_enqueued,
    process_export_task,
    recoverable_export_task_ids,
)


def enqueue_export(task_id: UUID) -> None:
    if get_settings().app_mock_mode:
        generate_export_task(str(task_id))
    else:
        generate_export_task.delay(str(task_id))


def get_export_enqueuer():
    return enqueue_export


@shared_task(name="exports.generate")
def generate_export_task(task_id: str) -> None:
    with SessionFactory() as session:
        process_export_task(session, UUID(task_id), get_storage())
        session.commit()


@shared_task(name="exports.recover_pending")
def recover_pending_export_tasks() -> None:
    with SessionFactory() as session:
        task_ids = recoverable_export_task_ids(session)
        for task_id in task_ids:
            try:
                generate_export_task.delay(str(task_id))
            except Exception:
                continue
            mark_export_enqueued(session, task_id)
        session.commit()
