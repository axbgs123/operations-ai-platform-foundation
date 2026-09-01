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
from app.modules.imports.ocr_adapters import VisionAdapter
from app.modules.imports.vision_binding import (
    VisionBinding,
    create_bound_vision_adapter,
)
from app.modules.models.config_service import SecretCipher
from app.modules.models.models import ModelConfig
from app.modules.models.capabilities import Capability
from app.modules.models.usage import (
    ProviderOperation,
    create_model_usage_governor,
)
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
        if (
            output.platform_confidence < MIN_RECOGNITION_CONFIDENCE
            and not output.requires_human_review
        ):
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
    if get_settings().run_tasks_inline:
        recognize_screenshot_task(str(batch_id))
    else:
        recognize_screenshot_task.delay(str(batch_id))


def get_screenshot_enqueuer():
    return enqueue_screenshot_recognition


@shared_task(name="imports.recognize_screenshot")
def recognize_screenshot_task(batch_id: str) -> None:
    settings = get_settings()
    parsed_id = UUID(batch_id)
    with SessionFactory() as session:
        batch = session.get(ImportBatch, parsed_id)
        if batch is None:
            raise LookupError("screenshot import batch not found")
        if batch.recognition_status == ScreenshotRecognitionStatus.READY:
            return
        batch.recognition_status = ScreenshotRecognitionStatus.PROCESSING
        batch.recognition_error = None
        binding = VisionBinding(
            model_config_id=batch.recognition_model_config_id,
            provider=batch.recognition_provider,
            model_id=batch.recognition_model_id,
            contract_version=batch.recognition_contract_version,
            config_version=batch.recognition_config_version,
            region=batch.recognition_region,
            metric_labels=dict(batch.recognition_metric_labels),
        )
        workspace_id = batch.workspace_id
        platform = batch.platform
        image = batch.screenshot_bytes
        mime_type = batch.screenshot_mime_type
        session.commit()
    try:
        if image is None or mime_type is None:
            raise ValueError("staged screenshot is unavailable")
        with SessionFactory() as session:
            config = (
                session.get(ModelConfig, binding.model_config_id)
                if binding.model_config_id is not None
                else None
            )
            adapter = create_bound_vision_adapter(
                session,
                workspace_id=workspace_id,
                expected_platform=platform,
                binding=binding,
                cipher=SecretCipher(
                    settings.model_secret_encryption_key.get_secret_value()
                ),
                mock_mode=settings.app_mock_mode,
                usage_governor=(
                    create_model_usage_governor(
                        session_factory=SessionFactory,
                        redis_url=settings.redis_url,
                        workspace_id=workspace_id,
                        model_config=config,
                        actor_id=batch.confirmed_by,
                        task_id=parsed_id,
                        capability=Capability.VISION,
                        operation=ProviderOperation.OCR,
                        contract_version=binding.contract_version,
                        configuration_version=binding.config_version,
                    )
                    if config is not None
                    and not settings.app_mock_mode
                    and not settings.app_lite_mode
                    else None
                ),
            )
        output = adapter.recognize(image, mime_type)

        class CompletedAdapter:
            def recognize(self, image: bytes, mime_type: str):
                return output

        with SessionFactory() as session:
            process_screenshot_recognition(
                session, parsed_id, CompletedAdapter()
            )
            session.commit()
    except Exception:
        with SessionFactory() as session:
            current = session.get(ImportBatch, parsed_id)
            if (
                current is not None
                and current.recognition_status
                != ScreenshotRecognitionStatus.READY
            ):
                current.recognition_status = ScreenshotRecognitionStatus.FAILED
                current.recognition_error = "screenshot recognition failed"
                session.commit()
