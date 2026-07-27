import os
from uuid import UUID

from celery import shared_task
from redis import Redis

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.core.storage import get_storage
from app.modules.exports.deletion import (
    ManagedObjectCleaner,
    purge_expired_trash,
    process_workspace_deletion,
)


class RedisWorkspaceCacheCleaner:
    def __init__(self, url: str | None = None) -> None:
        self._client = Redis.from_url(
            url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        )

    def clear_workspace(self, workspace_id: UUID) -> None:
        pattern = f"workspace:{workspace_id}:*"
        keys = list(self._client.scan_iter(match=pattern, count=100))
        if keys:
            self._client.delete(*keys)


def enqueue_workspace_deletion(job_id: UUID) -> None:
    if get_settings().app_mock_mode:
        workspace_deletion_task(str(job_id))
    else:
        workspace_deletion_task.delay(str(job_id))


@shared_task(name="exports.delete_workspace")
def workspace_deletion_task(job_id: str) -> None:
    with SessionFactory() as session:
        process_workspace_deletion(
            session,
            UUID(job_id),
            get_storage(),
            RedisWorkspaceCacheCleaner(),
        )


@shared_task(name="exports.cleanup_retained_objects")
def cleanup_retained_objects_task(workspace_id: str) -> None:
    with SessionFactory() as session:
        ManagedObjectCleaner(
            session,
            get_storage(),
        ).cleanup_due(UUID(workspace_id))
        purge_expired_trash(session, UUID(workspace_id))
        session.commit()
