import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from celery import shared_task
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.storage import Storage, get_storage
from app.modules.content.account_models import Platform
from app.modules.imports.capture_models import CaptureTask, CaptureTaskStatus
from app.modules.imports.vision_binding import (
    VisionBinding,
    create_bound_vision_adapter,
)
from app.modules.imports.ocr_adapters import MockVisionAdapter
from app.core.config import get_settings
from app.core.database import SessionFactory
from app.modules.models.config_service import SecretCipher
from app.modules.models.models import ModelConfig
from app.modules.models.capabilities import Capability
from app.modules.models.usage import (
    ProviderOperation,
    create_model_usage_governor,
)

MAX_CAPTURE_BYTES = 10 * 1024 * 1024
_OBJECTS: dict[str, bytes] = {}
_OBJECT_MIME: dict[str, str] = {}


class IdempotencyConflict(ValueError):
    pass


_TRANSITIONS = {
    CaptureTaskStatus.QUEUED: {CaptureTaskStatus.RUNNING, CaptureTaskStatus.CANCELLED},
    CaptureTaskStatus.RUNNING: {
        CaptureTaskStatus.SUCCEEDED,
        CaptureTaskStatus.FAILED,
        CaptureTaskStatus.RETRYING,
        CaptureTaskStatus.CANCELLED,
    },
    CaptureTaskStatus.RETRYING: {
        CaptureTaskStatus.RUNNING,
        CaptureTaskStatus.FAILED,
        CaptureTaskStatus.CANCELLED,
    },
    CaptureTaskStatus.SUCCEEDED: set(),
    CaptureTaskStatus.FAILED: {CaptureTaskStatus.RETRYING},
    CaptureTaskStatus.CANCELLED: set(),
}


def transition_task(task: CaptureTask, next_status: CaptureTaskStatus) -> None:
    if next_status not in _TRANSITIONS[task.status]:
        raise ValueError(
            f"illegal capture task transition: {task.status.value} -> {next_status.value}"
        )
    task.status = next_status


def _decode_image(data_url: str) -> tuple[str, bytes]:
    prefix, separator, encoded = data_url.partition(",")
    if separator != "," or not prefix.startswith("data:image/") or ";base64" not in prefix:
        raise ValueError("image must be a base64 data URL")
    mime = prefix.removeprefix("data:").removesuffix(";base64")
    if mime not in {"image/png", "image/jpeg", "image/webp"}:
        raise ValueError("unsupported image type")
    try:
        data = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise ValueError("invalid image encoding") from error
    if not data or len(data) > MAX_CAPTURE_BYTES:
        raise ValueError("image exceeds size limit")
    return mime, data


def create_task(
    session: Session,
    *,
    workspace_id: UUID,
    token_id: UUID,
    member_id: UUID,
    platform: Platform,
    page_version: str,
    page_identifier: str,
    collected_at: datetime,
    idempotency_key: str,
    screenshot_data_url: str,
    capture_metadata: dict[str, object],
    binding: VisionBinding,
    storage: Storage | None = None,
) -> CaptureTask:
    mime, image = _decode_image(screenshot_data_url)
    fingerprint = hashlib.sha256(
        b"|".join(
            [
                platform.value.encode(),
                page_version.encode(),
                page_identifier.encode(),
                collected_at.isoformat().encode(),
                json.dumps(capture_metadata, sort_keys=True, separators=(",", ":")).encode(),
                hashlib.sha256(image).hexdigest().encode(),
            ]
        )
    ).hexdigest()
    existing = session.scalar(
        select(CaptureTask).where(
            CaptureTask.workspace_id == workspace_id,
            CaptureTask.token_id == token_id,
            CaptureTask.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise IdempotencyConflict("idempotency key conflicts with another capture")
        return existing
    object_key = f"workspaces/{workspace_id}/capture/{secrets.token_urlsafe(16)}"
    if storage is None:
        _OBJECTS[object_key] = image
        _OBJECT_MIME[object_key] = mime
    else:
        storage.put_object(object_key, image, mime_type=mime)
    now = datetime.now(UTC)
    task = CaptureTask(
        workspace_id=workspace_id,
        token_id=token_id,
        member_id=member_id,
        platform=platform,
        page_version=page_version,
        page_identifier=page_identifier,
        collected_at=collected_at,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        object_key=object_key,
        status=CaptureTaskStatus.QUEUED,
        review_url=f"/workspaces/{workspace_id}/imports?capture_task_id=",
        expires_at=now + timedelta(hours=1),
        formal_snapshot_ids=[],
        model_config_id=binding.model_config_id,
        provider=binding.provider,
        model_id=binding.model_id,
        contract_version=binding.contract_version,
        config_version=binding.config_version,
        region=binding.region,
        metric_labels=binding.metric_labels,
        capture_metadata=capture_metadata,
    )
    session.add(task)
    session.flush()
    task.review_url += str(task.id)
    if binding.provider == "mock":
        transition_task(task, CaptureTaskStatus.RUNNING)
        output = MockVisionAdapter(platform).recognize(image, mime)
        task.recognition_output = output.model_dump(mode="json")
        transition_task(task, CaptureTaskStatus.SUCCEEDED)
    session.flush()
    return task


def process_capture_task(
    task_id: UUID | str,
    *,
    storage: Storage | None = None,
) -> None:
    parsed_id = UUID(str(task_id))
    settings = get_settings()
    with SessionFactory() as session:
        task = session.get(CaptureTask, parsed_id)
        if task is None:
            raise LookupError("capture task not found")
        if task.status in {
            CaptureTaskStatus.SUCCEEDED,
            CaptureTaskStatus.FAILED,
            CaptureTaskStatus.CANCELLED,
        }:
            return
        if task.status in {CaptureTaskStatus.QUEUED, CaptureTaskStatus.RETRYING}:
            transition_task(task, CaptureTaskStatus.RUNNING)
        binding = VisionBinding(
            model_config_id=task.model_config_id,
            provider=task.provider,
            model_id=task.model_id,
            contract_version=task.contract_version,
            config_version=task.config_version,
            region=task.region,
            metric_labels=dict(task.metric_labels),
        )
        workspace_id = task.workspace_id
        platform = task.platform
        object_key = task.object_key
        session.commit()
    try:
        if storage is None:
            image = _OBJECTS.get(object_key)
            mime_type = _OBJECT_MIME.get(object_key)
        else:
            stored = storage.inspect_object(object_key)
            image = storage.get_object(object_key) if stored is not None else None
            mime_type = stored.mime_type if stored is not None else None
        if image is None or mime_type is None:
            raise LookupError("capture image is unavailable")
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
                        actor_id=task.member_id,
                        task_id=parsed_id,
                        capability=Capability.VISION,
                        operation=ProviderOperation.OCR,
                        contract_version=binding.contract_version,
                        configuration_version=binding.config_version,
                    )
                    if config is not None and not settings.app_mock_mode
                    else None
                ),
            )
        output = adapter.recognize(image, mime_type)
    except Exception:
        with SessionFactory() as session:
            task = session.get(CaptureTask, parsed_id)
            if task is not None and task.status is CaptureTaskStatus.RUNNING:
                transition_task(task, CaptureTaskStatus.FAILED)
                task.error_code = "recognition_failed"
                session.commit()
        return
    with SessionFactory() as session:
        task = session.get(CaptureTask, parsed_id)
        if task is None or task.status is not CaptureTaskStatus.RUNNING:
            return
        task.recognition_output = output.model_dump(mode="json")
        transition_task(task, CaptureTaskStatus.SUCCEEDED)
        session.commit()


def enqueue_capture_task(task_id: UUID) -> None:
    if get_settings().app_mock_mode:
        process_capture_task(task_id)
    else:
        recognize_capture_task.delay(str(task_id))


def get_capture_enqueuer():
    return enqueue_capture_task


@shared_task(name="imports.recognize_extension_capture")
def recognize_capture_task(task_id: str) -> None:
    process_capture_task(task_id, storage=get_storage())


def task_payload(task: CaptureTask, request_id: str) -> dict[str, object]:
    return {
        "task_id": str(task.id),
        "workspace_id": str(task.workspace_id),
        "platform": task.platform.value,
        "page_version": task.page_version,
        "status": task.status.value,
        "request_id": request_id,
        "review_url": task.review_url,
        "expires_at": task.expires_at.isoformat(),
        "recognition": task.recognition_output,
        "error": task.error_code,
        "formal_snapshot_ids": task.formal_snapshot_ids,
        "provider_mode": "mock" if task.provider == "mock" else "qianwen",
        "region": task.region,
        "capture_metadata": task.capture_metadata,
    }


def clear_task_object(task: CaptureTask, *, storage: Storage | None = None) -> None:
    if storage is not None:
        storage.delete_object(task.object_key)
    _OBJECTS.pop(task.object_key, None)
    _OBJECT_MIME.pop(task.object_key, None)


def reset_capture_objects() -> None:
    _OBJECTS.clear()
    _OBJECT_MIME.clear()


def object_digest(task: CaptureTask) -> str | None:
    data = _OBJECTS.get(task.object_key)
    return hashlib.sha256(data).hexdigest() if data is not None else None
