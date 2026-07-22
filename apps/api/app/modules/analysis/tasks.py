from uuid import UUID

from celery import shared_task

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.modules.analysis.schemas import get_analysis_adapter
from app.modules.analysis.service import (
    begin_analysis_attempt,
    lease_recoverable_analysis_runs,
    process_analysis_run,
    record_analysis_provider_failure,
)


def enqueue_analysis(run_id: UUID) -> None:
    if get_settings().app_mock_mode:
        analyze_content_task(str(run_id))
    else:
        analyze_content_task.delay(str(run_id))


def get_analysis_enqueuer():
    return enqueue_analysis


def get_auto_analysis_enqueuer():
    return enqueue_analysis


@shared_task(name="analysis.analyze_content")
def analyze_content_task(run_id: str) -> None:
    parsed_run_id = UUID(run_id)
    with SessionFactory() as session:
        should_process = begin_analysis_attempt(session, parsed_run_id)
        session.commit()
    if not should_process:
        return
    try:
        with SessionFactory() as session:
            process_analysis_run(session, parsed_run_id, get_analysis_adapter())
            session.commit()
    except Exception:
        with SessionFactory() as session:
            record_analysis_provider_failure(session, parsed_run_id)
            session.commit()


@shared_task(name="analysis.recover_pending")
def recover_pending_analysis_task() -> None:
    with SessionFactory() as session:
        run_ids = lease_recoverable_analysis_runs(session)
        session.commit()
    for run_id in run_ids:
        analyze_content_task.delay(str(run_id))
