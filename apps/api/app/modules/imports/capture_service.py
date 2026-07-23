import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.content.account_models import Platform
from app.modules.imports.capture_models import CaptureTask, CaptureTaskStatus
from app.modules.imports.ocr_adapters import MockVisionAdapter

MAX_CAPTURE_BYTES = 10 * 1024 * 1024
_OBJECTS: dict[str, bytes] = {}


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
) -> CaptureTask:
    mime, image = _decode_image(screenshot_data_url)
    fingerprint = hashlib.sha256(
        b"|".join(
            [
                platform.value.encode(),
                page_version.encode(),
                page_identifier.encode(),
                collected_at.isoformat().encode(),
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
    _OBJECTS[object_key] = image
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
    )
    session.add(task)
    session.flush()
    task.review_url += str(task.id)
    transition_task(task, CaptureTaskStatus.RUNNING)
    session.flush()
    try:
        output = MockVisionAdapter(platform).recognize(image, mime)
        task.recognition_output = output.model_dump(mode="json")
        transition_task(task, CaptureTaskStatus.SUCCEEDED)
    except Exception:
        if task.status == CaptureTaskStatus.RUNNING:
            transition_task(task, CaptureTaskStatus.FAILED)
        task.error_code = "recognition_failed"
    session.flush()
    return task


def task_payload(task: CaptureTask, request_id: str) -> dict[str, object]:
    return {
        "task_id": str(task.id),
        "workspace_id": str(task.workspace_id),
        "status": task.status.value,
        "request_id": request_id,
        "review_url": task.review_url,
        "expires_at": task.expires_at.isoformat(),
        "recognition": task.recognition_output,
        "error": task.error_code,
        "formal_snapshot_ids": task.formal_snapshot_ids,
    }


def clear_task_object(task: CaptureTask) -> None:
    _OBJECTS.pop(task.object_key, None)


def reset_capture_objects() -> None:
    _OBJECTS.clear()


def object_digest(task: CaptureTask) -> str | None:
    data = _OBJECTS.get(task.object_key)
    return hashlib.sha256(data).hexdigest() if data is not None else None
