from uuid import UUID

from celery import shared_task

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.core.storage import get_storage
from app.modules.hotspots.models import HotspotCaptureStatus, HotspotCaptureTask
from app.modules.hotspots.service import capture_image, set_recognition_result
from app.modules.imports.vision_binding import (
    VisionBinding,
    create_bound_vision_adapter,
)
from app.modules.models.capabilities import Capability
from app.modules.models.config_service import SecretCipher
from app.modules.models.models import ModelConfig
from app.modules.models.usage import (
    ProviderOperation,
    create_model_usage_governor,
)


def process_hotspot_capture(task_id: UUID | str) -> None:
    parsed_id = UUID(str(task_id))
    settings = get_settings()
    storage = get_storage()
    with SessionFactory() as session:
        task = session.get(HotspotCaptureTask, parsed_id)
        if task is None:
            raise LookupError("hotspot capture not found")
        if task.status in {
            HotspotCaptureStatus.REVIEW_READY,
            HotspotCaptureStatus.CONFIRMED,
            HotspotCaptureStatus.CANCELLED,
        }:
            return
        if task.status is not HotspotCaptureStatus.QUEUED:
            return
        task.status = HotspotCaptureStatus.RUNNING
        binding = VisionBinding(
            model_config_id=task.model_config_id,
            provider=task.provider,
            model_id=task.model_id,
            contract_version=task.contract_version,
            config_version=task.configuration_version,
            region=task.region,
            metric_labels={},
        )
        workspace_id = task.workspace_id
        platform = task.target_platform
        member_id = task.member_id
        session.commit()
    try:
        with SessionFactory() as session:
            task = session.get(HotspotCaptureTask, parsed_id)
            if task is None:
                return
            image = capture_image(task, storage)
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
                mock_mode=False,
                usage_governor=(
                    create_model_usage_governor(
                        session_factory=SessionFactory,
                        redis_url=settings.redis_url,
                        workspace_id=workspace_id,
                        model_config=config,
                        actor_id=member_id,
                        task_id=parsed_id,
                        capability=Capability.VISION,
                        operation=ProviderOperation.OCR,
                        contract_version=binding.contract_version,
                        configuration_version=binding.config_version,
                    )
                    if config is not None
                    else None
                ),
            )
        output = adapter.recognize(image, "image/png")
        ordered_regions = sorted(
            output.text_regions,
            key=lambda item: (item.region.y, item.region.x),
        )
        lines = [item.text for item in ordered_regions]
        lines.extend(output.unmapped_text)
    except Exception:
        with SessionFactory() as session:
            task = session.get(HotspotCaptureTask, parsed_id)
            if task is not None and task.status is HotspotCaptureStatus.RUNNING:
                task.status = HotspotCaptureStatus.FAILED
                task.error_code = "HOTSPOT_OCR_FAILED"
                session.commit()
        return
    with SessionFactory() as session:
        task = session.get(HotspotCaptureTask, parsed_id)
        if task is None or task.status is not HotspotCaptureStatus.RUNNING:
            return
        set_recognition_result(task, text_lines=lines)
        session.commit()


def enqueue_hotspot_capture(task_id: UUID) -> None:
    recognize_hotspot_capture.delay(str(task_id))


def get_hotspot_enqueuer():
    return enqueue_hotspot_capture


@shared_task(name="hotspots.recognize_capture")
def recognize_hotspot_capture(task_id: str) -> None:
    process_hotspot_capture(task_id)
