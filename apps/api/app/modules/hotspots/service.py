from __future__ import annotations

import base64
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
import json
import re
import secrets
from typing import TypedDict
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.storage import Storage
from app.modules.content.account_models import Platform
from app.modules.hotspots.models import (
    CaptureCompleteness,
    HotspotCaptureStatus,
    HotspotCaptureTask,
    HotspotEntry,
    HotspotSnapshot,
)
from app.modules.imports.vision_binding import VisionBinding


MAX_CAPTURE_BYTES = 10 * 1024 * 1024
MAX_CAPTURE_PIXELS = 25_000_000
MAX_HOTSPOT_ENTRIES = 50
_RANKED_LINE = re.compile(
    r"^\s*(?P<rank>[1-9][0-9]{0,2})[.、)）\s]+(?P<topic>.+?)"
    r"(?:\s+(?P<heat>[0-9][0-9,.]*(?:万|亿|w|W|k|K)?))?\s*$"
)
_MOCK_OBJECTS: dict[str, bytes] = {}


class HotspotConflict(ValueError):
    pass


class _NormalizedEntry(TypedDict):
    position: int
    topic: str
    rank: int | None
    heat: str | None
    selected: bool


def normalize_source_url(value: str) -> tuple[str, str]:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("source_url must be a public HTTPS URL")
    host = parsed.hostname.lower().rstrip(".")
    if not host or len(host) > 253:
        raise ValueError("source_url host is invalid")
    normalized = urlunsplit(("https", parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))
    if len(normalized) > 2_000:
        raise ValueError("source_url is too long")
    return normalized, host


def sanitize_capture(data_url: str) -> tuple[str, bytes]:
    prefix, separator, encoded = data_url.partition(",")
    if separator != "," or not prefix.startswith("data:image/") or ";base64" not in prefix:
        raise ValueError("screenshot must be a base64 image data URL")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise ValueError("screenshot encoding is invalid") from error
    if not raw or len(raw) > MAX_CAPTURE_BYTES:
        raise ValueError("screenshot exceeds size limit")
    try:
        with Image.open(BytesIO(raw)) as opened:
            if opened.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("screenshot type is unsupported")
            width, height = opened.size
            if width <= 0 or height <= 0 or width * height > MAX_CAPTURE_PIXELS:
                raise ValueError("screenshot dimensions exceed limit")
            opened.load()
            safe = opened.convert("RGBA" if "A" in opened.getbands() else "RGB")
            output = BytesIO()
            safe.save(output, format="PNG", optimize=True)
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as error:
        raise ValueError("screenshot cannot be decoded") from error
    return "image/png", output.getvalue()


def extract_candidates(lines: Sequence[str]) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw in enumerate(lines):
        text = " ".join(raw.split()).strip()
        if not text:
            continue
        match = _RANKED_LINE.fullmatch(text)
        rank = int(match.group("rank")) if match else None
        topic = (match.group("topic") if match else text).strip(" -—:：")
        heat = match.group("heat") if match else None
        topic = topic[:300]
        key = topic.casefold()
        if not topic or key in seen:
            continue
        seen.add(key)
        candidates.append(
            {
                "position": len(candidates) + 1,
                "rank": rank,
                "topic": topic,
                "heat": heat,
                "ocr_text_index": index,
            }
        )
        if len(candidates) >= MAX_HOTSPOT_ENTRIES:
            break
    return candidates


def create_capture(
    session: Session,
    *,
    workspace_id: UUID,
    member_id: UUID,
    target_platform: Platform,
    source_url: str,
    page_title: str,
    collected_at: datetime,
    completeness: CaptureCompleteness,
    idempotency_key: str,
    screenshot_data_url: str,
    binding: VisionBinding,
    storage: Storage | None,
) -> HotspotCaptureTask:
    if collected_at.tzinfo is None:
        raise ValueError("collected_at must include timezone")
    normalized_url, source_host = normalize_source_url(source_url)
    mime_type, image = sanitize_capture(screenshot_data_url)
    image_hash = sha256(image).hexdigest()
    fingerprint = sha256(
        json.dumps(
            {
                "platform": target_platform.value,
                "source_url": normalized_url,
                "title": page_title.strip(),
                "collected_at": collected_at.astimezone(UTC).isoformat(),
                "completeness": completeness.value,
                "image_sha256": image_hash,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    existing = session.scalar(
        select(HotspotCaptureTask).where(
            HotspotCaptureTask.workspace_id == workspace_id,
            HotspotCaptureTask.member_id == member_id,
            HotspotCaptureTask.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise HotspotConflict("idempotency key conflicts with another capture")
        return existing
    object_key = f"workspaces/{workspace_id}/hotspot-captures/{secrets.token_urlsafe(20)}.png"
    if storage is None:
        _MOCK_OBJECTS[object_key] = image
    else:
        storage.put_object(object_key, image, mime_type=mime_type)
    task = HotspotCaptureTask(
        workspace_id=workspace_id,
        member_id=member_id,
        target_platform=target_platform,
        source_url=normalized_url,
        source_host=source_host,
        page_title=page_title.strip(),
        collected_at=collected_at.astimezone(UTC),
        completeness=completeness,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        image_sha256=image_hash,
        object_key=object_key,
        mime_type=mime_type,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        status=HotspotCaptureStatus.QUEUED,
        model_config_id=binding.model_config_id,
        provider=binding.provider,
        model_id=binding.model_id,
        contract_version=binding.contract_version,
        configuration_version=binding.config_version,
        region=binding.region,
    )
    session.add(task)
    session.flush()
    if binding.provider == "mock":
        task.status = HotspotCaptureStatus.REVIEW_READY
        task.candidate_entries = extract_candidates(
            (
                "1 AI 视频生成工具更新 982万",
                "2 多模态智能体落地 765万",
                "3 内容运营自动化 621万",
            )
        )
        session.flush()
    return task


def capture_image(task: HotspotCaptureTask, storage: Storage | None) -> bytes:
    if storage is None:
        image = _MOCK_OBJECTS.get(task.object_key)
        if image is None:
            raise LookupError("hotspot screenshot is unavailable")
        return image
    stored = storage.inspect_object(task.object_key)
    if stored is None:
        raise LookupError("hotspot screenshot is unavailable")
    return storage.get_object(task.object_key)


def set_recognition_result(
    task: HotspotCaptureTask,
    *,
    text_lines: Sequence[str],
) -> None:
    candidates = extract_candidates(text_lines)
    if not candidates:
        task.status = HotspotCaptureStatus.FAILED
        task.error_code = "HOTSPOT_OCR_EMPTY"
        return
    task.candidate_entries = candidates
    task.error_code = None
    task.status = HotspotCaptureStatus.REVIEW_READY


def _normalized_confirmation(
    entries: Sequence[dict[str, object]],
) -> list[_NormalizedEntry]:
    if not entries or len(entries) > MAX_HOTSPOT_ENTRIES:
        raise ValueError("between 1 and 50 hotspot entries are required")
    normalized: list[_NormalizedEntry] = []
    topics: set[str] = set()
    for position, entry in enumerate(entries, start=1):
        topic = " ".join(str(entry.get("topic", "")).split()).strip()
        if not topic or len(topic) > 300:
            raise ValueError("hotspot topic is invalid")
        key = topic.casefold()
        if key in topics:
            raise ValueError("duplicate hotspot topic")
        topics.add(key)
        raw_rank = entry.get("rank")
        if raw_rank is None:
            rank = None
        elif isinstance(raw_rank, int) and not isinstance(raw_rank, bool):
            rank = raw_rank
        else:
            raise ValueError("hotspot rank is invalid")
        if rank is not None and not 1 <= rank <= 999:
            raise ValueError("hotspot rank is invalid")
        raw_heat = entry.get("heat")
        heat = " ".join(str(raw_heat).split())[:80] if raw_heat else None
        normalized.append(
            {
                "position": position,
                "topic": topic,
                "rank": rank,
                "heat": heat,
                "selected": bool(entry.get("selected", True)),
            }
        )
    return normalized


def confirm_capture(
    session: Session,
    *,
    task: HotspotCaptureTask,
    confirmed_by: UUID,
    entries: Sequence[dict[str, object]],
    storage: Storage | None,
) -> HotspotSnapshot:
    normalized = _normalized_confirmation(entries)
    fingerprint = sha256(
        json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if task.confirmed_snapshot_id is not None:
        if task.confirmation_fingerprint != fingerprint:
            raise HotspotConflict("capture was already confirmed with different entries")
        snapshot = session.get(HotspotSnapshot, task.confirmed_snapshot_id)
        if snapshot is None:
            raise LookupError("confirmed hotspot snapshot is unavailable")
        return snapshot
    if task.status is not HotspotCaptureStatus.REVIEW_READY:
        raise HotspotConflict("hotspot capture is not ready for confirmation")
    now = datetime.now(UTC)
    snapshot = HotspotSnapshot(
        workspace_id=task.workspace_id,
        capture_task_id=task.id,
        confirmed_by=confirmed_by,
        target_platform=task.target_platform,
        source_url=task.source_url,
        source_host=task.source_host,
        page_title=task.page_title,
        collected_at=task.collected_at,
        confirmed_at=now,
        completeness=task.completeness,
        ocr_model_id=task.model_id,
        ocr_contract_version=task.contract_version,
        entry_count=len(normalized),
    )
    session.add(snapshot)
    session.flush()
    for entry in normalized:
        session.add(
            HotspotEntry(
                snapshot_id=snapshot.id,
                position=entry["position"],
                topic=entry["topic"],
                rank=entry["rank"],
                heat=entry["heat"],
                selected=entry["selected"],
            )
        )
    if storage is None:
        _MOCK_OBJECTS.pop(task.object_key, None)
    else:
        storage.delete_object(task.object_key)
    task.status = HotspotCaptureStatus.CONFIRMED
    task.confirmed_snapshot_id = snapshot.id
    task.confirmation_fingerprint = fingerprint
    task.object_deleted_at = now
    session.flush()
    return snapshot


def reset_hotspot_objects() -> None:
    _MOCK_OBJECTS.clear()
