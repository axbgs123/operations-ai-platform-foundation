from uuid import UUID

from celery import shared_task
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.modules.imports.dedupe import classify_duplicate
from app.modules.imports.models import (
    ImportBatch,
    ImportRow,
    ImportRowStatus,
    ImportSourceKind,
    ScreenshotRecognitionStatus,
)
from app.modules.imports.ocr_adapters import VisionAdapter, get_vision_adapter
from app.modules.imports.parsers.tabular import normalize_manual_row


MIN_RECOGNITION_CONFIDENCE = 0.8


def process_screenshot_recognition(
    session: Session,
    batch_id: UUID | str,
    adapter: VisionAdapter,
) -> None:
    batch = session.scalar(
        select(ImportBatch)
        .where(
            ImportBatch.id == UUID(str(batch_id)),
            ImportBatch.source_kind == ImportSourceKind.SCREENSHOT,
        )
        .with_for_update()
    )
    if batch is None:
        raise LookupError("screenshot import batch not found")
    if batch.recognition_status == ScreenshotRecognitionStatus.READY:
        return
    batch.recognition_status = ScreenshotRecognitionStatus.PROCESSING
    batch.recognition_error = None
    session.flush()
    try:
        if batch.screenshot_bytes is None or batch.screenshot_mime_type is None:
            raise ValueError("staged screenshot is unavailable")
        output = adapter.recognize(
            batch.screenshot_bytes,
            batch.screenshot_mime_type,
        )
        structured = output.model_dump(mode="json")
        metadata = dict(batch.screenshot_metadata or {})
        errors: list[dict[str, str]] = []
        if output.platform_confidence < MIN_RECOGNITION_CONFIDENCE:
            errors.append(
                {"field": "platform", "message": "platform confidence is too low"}
            )
        elif output.platform != batch.platform.value:
            errors.append(
                {
                    "field": "platform",
                    "message": "recognized platform conflicts with selected account",
                }
            )

        identifier = output.content_identifier
        if identifier and identifier.confidence >= MIN_RECOGNITION_CONFIDENCE:
            metadata["platform_content_id"] = identifier.platform_content_id
            metadata["work_url"] = identifier.work_url
        metrics = {
            candidate.key: candidate.value
            for candidate in output.metric_candidates
            if candidate.confidence >= MIN_RECOGNITION_CONFIDENCE
        }
        confidences = {
            candidate.key: candidate.confidence
            for candidate in output.metric_candidates
            if candidate.confidence >= MIN_RECOGNITION_CONFIDENCE
        }
        metadata["metrics"] = metrics
        normalized, errors = normalize_manual_row(
            metadata,
            batch.platform,
            batch.content_type,
            errors=errors,
        )
        normalized["metric_confidences"] = confidences
        if errors:
            status, matched_content_id, reason = ImportRowStatus.FAILED, None, None
        else:
            status, matched_content_id, reason = classify_duplicate(
                session,
                workspace_id=batch.workspace_id,
                account_id=batch.account_id,
                platform=batch.platform,
                normalized_data=normalized,
            )
        session.execute(delete(ImportRow).where(ImportRow.batch_id == batch.id))
        session.add(
            ImportRow(
                workspace_id=batch.workspace_id,
                batch_id=batch.id,
                row_number=1,
                raw_data=structured,
                normalized_data=normalized,
                errors=errors,
                status=status,
                matched_content_id=matched_content_id,
                dedupe_reason=reason,
            )
        )
        batch.recognition_output = structured
        batch.recognition_status = ScreenshotRecognitionStatus.READY
        session.flush()
    except Exception:
        session.rollback()
        batch = session.get(ImportBatch, UUID(str(batch_id)))
        if batch is None:
            raise
        batch.recognition_status = ScreenshotRecognitionStatus.FAILED
        batch.recognition_error = "screenshot recognition failed"
        session.flush()


def enqueue_screenshot_recognition(batch_id: UUID) -> None:
    if get_settings().app_mock_mode:
        recognize_screenshot_task(str(batch_id))
    else:
        recognize_screenshot_task.delay(str(batch_id))


def get_screenshot_enqueuer():
    return enqueue_screenshot_recognition


@shared_task(name="imports.recognize_screenshot")
def recognize_screenshot_task(batch_id: str) -> None:
    with SessionFactory() as session:
        batch = session.get(ImportBatch, UUID(batch_id))
        if batch is None:
            raise LookupError("screenshot import batch not found")
        adapter = get_vision_adapter(batch.platform)
        process_screenshot_recognition(session, batch.id, adapter)
        session.commit()
