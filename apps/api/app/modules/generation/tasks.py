from uuid import UUID

from celery import shared_task

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.core.logging import current_request_id, task_request_context
from app.core.observability import record_task_correlation
from app.modules.generation.models import TextGenerationRun, TextGenerationRunStatus
from app.modules.generation.text_service import process_text_generation


def enqueue_text_generation(run_id: UUID) -> None:
    request_id = current_request_id()
    if get_settings().app_mock_mode:
        generate_text_task(str(run_id), request_id)
    else:
        generate_text_task.delay(str(run_id), request_id)


def get_text_generation_enqueuer():
    return enqueue_text_generation


@shared_task(name="generation.generate_text")
def generate_text_task(run_id: str, request_id: str | None = None) -> None:
    with task_request_context(request_id) as safe_request_id:
        with SessionFactory() as session:
            parsed_id = UUID(run_id)
            run = session.get(TextGenerationRun, parsed_id)
            if run is not None:
                record_task_correlation(
                    session,
                    workspace_id=run.workspace_id,
                    task_id=run.id,
                    task_type="generation",
                    request_id=safe_request_id,
                )
                if run.status == TextGenerationRunStatus.QUEUED:
                    run.status = TextGenerationRunStatus.RUNNING
                session.commit()
            process_text_generation(
                session,
                parsed_id,
                model_available=get_settings().app_mock_mode,
            )
            session.commit()
