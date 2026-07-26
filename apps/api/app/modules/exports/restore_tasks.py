from uuid import UUID

from celery import shared_task

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.core.storage import get_storage
from app.modules.exports.zip_restore import process_full_restore_task


def enqueue_restore(task_id: UUID) -> None:
    if get_settings().app_mock_mode:
        restore_workspace_task(str(task_id))
    else:
        restore_workspace_task.delay(str(task_id))


def get_restore_enqueuer():
    return enqueue_restore


@shared_task(name="exports.restore_workspace")
def restore_workspace_task(task_id: str) -> None:
    with SessionFactory() as session:
        process_full_restore_task(
            session,
            UUID(task_id),
            get_storage(),
        )
