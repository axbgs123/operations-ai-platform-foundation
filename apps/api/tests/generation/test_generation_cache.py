from datetime import timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.modules.generation.models import TextGenerationRunStatus
from app.modules.generation.text_service import (
    cancel_text_generation,
    create_text_generation,
    edit_text_generation,
    process_text_generation,
    retry_text_generation,
)
from app.modules.models.models import ModelConfig  # noqa: F401
from app.modules.workspace.models import AuditLog
from tests.generation.test_text_generation import _context


class FailingAdapter:
    async def generate(self, request):
        raise ConnectionError("provider payload must not reach logs")


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_successful_semantic_context_is_cached():
    with _session() as session:
        context = _context()
        first, should_enqueue = create_text_generation(session, context)
        assert should_enqueue is True
        process_text_generation(session, first.id)

        equivalent = context.model_copy(
            update={
                "id": context.id,
                "created_at": context.created_at + timedelta(minutes=2),
            }
        )
        second, should_enqueue = create_text_generation(session, equivalent)

        assert second.id == first.id
        assert should_enqueue is False
        assert second.status is TextGenerationRunStatus.SUCCEEDED


def test_cancel_and_retry_reuse_frozen_context_in_a_new_run():
    with _session() as session:
        context = _context()
        original, _ = create_text_generation(session, context)

        cancelled = cancel_text_generation(session, original.id)
        retried = retry_text_generation(session, cancelled.id)

        assert cancelled.status is TextGenerationRunStatus.CANCELLED
        assert retried.id != cancelled.id
        assert retried.retry_of_run_id == cancelled.id
        assert retried.context == cancelled.context
        assert retried.status is TextGenerationRunStatus.QUEUED


def test_unavailable_model_has_explicit_degradation_status():
    with _session() as session:
        run, _ = create_text_generation(session, _context())

        failed = process_text_generation(
            session,
            run.id,
            model_available=False,
        )

        assert failed.status is TextGenerationRunStatus.FAILED
        assert failed.error_code == "MODEL_ADAPTER_UNAVAILABLE"
        assert failed.status_detail == "请配置可用的文本模型后重试。"
        assert failed.original_result is None


def test_provider_exception_does_not_leave_run_running():
    with _session() as session:
        run, _ = create_text_generation(session, _context())

        failed = process_text_generation(
            session,
            run.id,
            adapter=FailingAdapter(),
        )

        assert failed.status is TextGenerationRunStatus.FAILED
        assert failed.error_code == "MODEL_GENERATION_FAILED"
        assert "provider payload" not in (failed.status_detail or "")


def test_edit_preserves_original_records_adoption_and_redacted_audit():
    with _session() as session:
        run, _ = create_text_generation(session, _context())
        process_text_generation(session, run.id)
        original = dict(run.original_result or {})

        updated = edit_text_generation(
            session,
            run.id,
            final_title="人工标题",
            final_copy="人工修改后的完整文案，不能进入审计日志。",
            adoption_status="adopted",
        )

        assert updated.original_result == original
        assert updated.final_title == "人工标题"
        assert updated.adoption_status == "adopted"
        assert 0 < updated.modification_magnitude <= 1
        audit = session.scalar(select(AuditLog).where(AuditLog.resource_id == run.id))
        assert audit is not None
        serialized = str(audit.details)
        assert "人工修改后的完整文案" not in serialized
        assert set(audit.details) == {
            "adoption_status",
            "modification_magnitude",
            "final_title_length",
            "final_copy_length",
        }
