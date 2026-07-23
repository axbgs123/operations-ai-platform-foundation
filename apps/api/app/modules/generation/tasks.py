from uuid import UUID

from celery import shared_task

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.modules.generation.text_service import process_text_generation


def enqueue_text_generation(run_id: UUID) -> None:
    if get_settings().app_mock_mode:
        generate_text_task(str(run_id))
    else:
        generate_text_task.delay(str(run_id))


def get_text_generation_enqueuer():
    return enqueue_text_generation


@shared_task(name="generation.generate_text")
def generate_text_task(run_id: str) -> None:
    with SessionFactory() as session:
        process_text_generation(
            session,
            UUID(run_id),
            model_available=get_settings().app_mock_mode,
        )
        session.commit()
