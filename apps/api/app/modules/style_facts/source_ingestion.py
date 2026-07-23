from datetime import datetime
import hashlib
from io import BytesIO
from pathlib import PurePath
import re
from typing import TypedDict
from uuid import UUID
import warnings
import zipfile

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.database import utc_now
from app.core.security import WorkspaceContext
from app.modules.style_facts.fact_models import (
    FactConflictStatus,
    FactItem,
    FactItemStatus,
    FactSource,
    FactSourceKind,
    FactSourceLevel,
    FactSourceStatus,
)
from app.modules.style_facts.url_safety import validate_source_url
from app.modules.workspace.models import AuditLog
from app.modules.workspace.permissions import Permission, require_permission


MAX_DOCUMENT_SIZE = 20 * 1024 * 1024
MAX_IMAGE_SIZE = 10 * 1024 * 1024


class FactUploadTooLarge(ValueError):
    pass


class FactContext(TypedDict):
    unconstrained_facts: bool
    has_sources: bool
    requires_confirmation: bool
    confirmed_items: list[FactItem]


_FILE_TYPES: dict[str, tuple[FactSourceKind, str]] = {
    ".txt": (FactSourceKind.DOCUMENT, "text/plain"),
    ".pdf": (FactSourceKind.DOCUMENT, "application/pdf"),
    ".docx": (
        FactSourceKind.DOCUMENT,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    ".png": (FactSourceKind.IMAGE, "image/png"),
    ".jpg": (FactSourceKind.IMAGE, "image/jpeg"),
    ".jpeg": (FactSourceKind.IMAGE, "image/jpeg"),
    ".webp": (FactSourceKind.IMAGE, "image/webp"),
}
_RESERVED_FIELDS = {
    "assistant",
    "developer",
    "instruction",
    "prompt",
    "role",
    "system",
    "系统",
    "系统指令",
}
_CONFIDENCE = {
    FactSourceLevel.L1: 1.0,
    FactSourceLevel.L2: 1.0,
    FactSourceLevel.L3: 0.85,
    FactSourceLevel.L4: 0.65,
    FactSourceLevel.L5: 0.4,
}


def _is_reserved_field(field_name: str) -> bool:
    normalized_field = re.sub(r"[\W_]+", "", field_name.casefold())
    return field_name.casefold() in _RESERVED_FIELDS or normalized_field.startswith(
        (
            "assistant",
            "developer",
            "instruction",
            "ignorepreviousinstruction",
            "ignoreallprevious",
            "disregardprevious",
            "overrideinstruction",
            "admininstruction",
            "administratorinstruction",
            "prompt",
            "role",
            "system",
            "系统指令",
            "系统提示词",
            "提示词",
            "管理员指令",
            "管理员提示",
            "忽略之前指令",
            "忽略所有指令",
            "覆盖系统规则",
        )
    )


def _valid_docx(content: bytes) -> bool:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            members = archive.infolist()
            names = {member.filename for member in members}
            if not {"[Content_Types].xml", "word/document.xml"} <= names:
                return False
            total = sum(member.file_size for member in members)
            compressed = sum(max(member.compress_size, 1) for member in members)
            if total > 50 * 1024 * 1024 or total > compressed * 100:
                return False
            archive.read("[Content_Types].xml")
            archive.read("word/document.xml")
            return archive.testzip() is None
    except (OSError, KeyError, zipfile.BadZipFile, RuntimeError):
        return False


def _valid_pdf(content: bytes) -> bool:
    try:
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.trailer.get("/Root") is None or not 1 <= len(reader.pages) <= 500:
            return False
        for page in reader.pages:
            if page.mediabox.width <= 0 or page.mediabox.height <= 0:
                return False
        return True
    except (PdfReadError, OSError, ValueError, TypeError, KeyError):
        return False


def _valid_image(extension: str, content: bytes) -> bool:
    expected_format = {
        ".png": "PNG",
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".webp": "WEBP",
    }[extension]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                if image.format != expected_format:
                    return False
                if image.width * image.height > 40_000_000:
                    return False
                if getattr(image, "n_frames", 1) > 100:
                    return False
                image.verify()
        return True
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
    ):
        return False


def _valid_signature(extension: str, content: bytes) -> bool:
    if extension == ".txt":
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return True
    if extension == ".pdf":
        return _valid_pdf(content)
    if extension == ".docx":
        return _valid_docx(content)
    if extension in {".png", ".jpg", ".jpeg", ".webp"}:
        return _valid_image(extension, content)
    return False


def parse_candidate_lines(text: str) -> list[tuple[str, str, str]]:
    candidates: list[tuple[str, str, str]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        match = re.match(r"^([^：:]{1,120})[：:]\s*(.{1,5000})$", line)
        if match is None:
            continue
        field_name = match.group(1).strip()
        value = match.group(2).strip()
        if _is_reserved_field(field_name):
            continue
        candidates.append((field_name, value, f"line {line_number}"))
    return candidates


class FactSourceService:
    def __init__(self, session: Session, context: WorkspaceContext) -> None:
        self._session = session
        self._context = context

    def _add_items(self, source: FactSource, text: str) -> list[FactItem]:
        items = [
            FactItem(
                workspace_id=self._context.workspace_id,
                source_id=source.id,
                field_name=field_name,
                value=value,
                source_location=location,
                confidence=_CONFIDENCE[source.level],
                status=FactItemStatus.CANDIDATE,
                conflict_status=FactConflictStatus.CLEAR,
            )
            for field_name, value, location in parse_candidate_lines(text)
        ]
        self._session.add_all(items)
        self._session.flush()
        return items

    def _add_structured_items(
        self,
        source: FactSource,
        candidates: list[tuple[str, str, str, float]],
    ) -> list[FactItem]:
        items = [
            FactItem(
                workspace_id=self._context.workspace_id,
                source_id=source.id,
                field_name=field_name,
                value=value,
                source_location=source_location,
                confidence=confidence,
                status=FactItemStatus.CANDIDATE,
                conflict_status=FactConflictStatus.CLEAR,
            )
            for field_name, value, source_location, confidence in candidates
            if not _is_reserved_field(field_name)
        ]
        self._session.add_all(items)
        self._session.flush()
        return items

    def create_source(
        self,
        *,
        kind: FactSourceKind,
        level: FactSourceLevel,
        title: str,
        content: str,
        url: str | None = None,
        published_at: datetime | None = None,
    ) -> FactSource:
        require_permission(self._context.role, Permission.MANAGE_FACTS)
        if kind not in {FactSourceKind.TEXT, FactSourceKind.LINK, FactSourceKind.WEB}:
            raise ValueError("JSON fact source must be text, link, or web")
        source_url = None
        resolved_ips: list[str] = []
        accessed_at = None
        if kind in {FactSourceKind.LINK, FactSourceKind.WEB}:
            if level is not FactSourceLevel.L4:
                raise ValueError("link and web sources must use L4")
            if url is None:
                raise ValueError("link and web sources require a URL")
            validated_url = validate_source_url(url)
            source_url = validated_url.url
            resolved_ips = list(validated_url.resolved_ips)
        elif url is not None:
            raise ValueError("text sources cannot include a URL")
        source = FactSource(
            workspace_id=self._context.workspace_id,
            kind=kind,
            level=level,
            title=title,
            status=(
                FactSourceStatus.PARSED
                if content.strip()
                else FactSourceStatus.AWAITING_FETCH
            ),
            source_url=source_url,
            resolved_ips=resolved_ips,
            source_text=content,
            content_sha256=hashlib.sha256(content.encode()).hexdigest(),
            published_at=published_at,
            accessed_at=accessed_at,
            created_by=self._context.member_id,
            status_detail=(
                {"code": "USER_SUPPLIED_SNAPSHOT", "network_fetched": False}
                if kind in {FactSourceKind.LINK, FactSourceKind.WEB}
                and content.strip()
                else {}
            ),
        )
        self._session.add(source)
        self._session.flush()
        if content.strip():
            self._add_items(source, content)
        return source

    def upload_source(
        self,
        *,
        kind: FactSourceKind,
        level: FactSourceLevel,
        title: str,
        file_name: str,
        mime_type: str,
        content: bytes,
    ) -> FactSource:
        require_permission(self._context.role, Permission.MANAGE_FACTS)
        if kind not in {FactSourceKind.DOCUMENT, FactSourceKind.IMAGE}:
            raise ValueError("uploaded fact source must be a document or image")
        maximum = MAX_IMAGE_SIZE if kind is FactSourceKind.IMAGE else MAX_DOCUMENT_SIZE
        if len(content) > maximum:
            raise FactUploadTooLarge("fact source file exceeds the allowed size")
        extension = PurePath(file_name).suffix.lower()
        expected = _FILE_TYPES.get(extension)
        if expected is None or expected != (kind, mime_type):
            raise ValueError("fact source extension and MIME type do not match")
        if not _valid_signature(extension, content):
            raise ValueError("fact source file signature is invalid")

        plain_text = content.decode() if extension == ".txt" else None
        required_capability = "vision" if kind is FactSourceKind.IMAGE else "text"
        source = FactSource(
            workspace_id=self._context.workspace_id,
            kind=kind,
            level=level,
            title=title,
            status=(
                FactSourceStatus.PARSED
                if plain_text is not None
                else FactSourceStatus.AWAITING_MODEL
            ),
            file_name=file_name,
            mime_type=mime_type,
            size=len(content),
            content_sha256=hashlib.sha256(content).hexdigest(),
            raw_content=content,
            source_text=plain_text,
            created_by=self._context.member_id,
            status_detail=(
                {}
                if plain_text is not None
                else {
                    "code": "MODEL_CONFIGURATION_REQUIRED",
                    "action": "configure_model",
                    "required_capabilities": [required_capability],
                }
            ),
        )
        self._session.add(source)
        self._session.flush()
        if plain_text is not None:
            self._add_items(source, plain_text)
        return source

    def source(self, source_id: UUID) -> FactSource:
        require_permission(self._context.role, Permission.READ_CONTENT)
        source = self._session.scalar(
            select(FactSource).where(
                FactSource.id == source_id,
                FactSource.workspace_id == self._context.workspace_id,
            )
        )
        if source is None:
            raise LookupError("fact source not found")
        return source

    def sources(self) -> list[FactSource]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        return list(
            self._session.scalars(
                select(FactSource)
                .where(FactSource.workspace_id == self._context.workspace_id)
                .order_by(FactSource.created_at, FactSource.id)
            )
        )

    def items(self, source_id: UUID | None = None) -> list[FactItem]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        query = select(FactItem).where(
            FactItem.workspace_id == self._context.workspace_id
        )
        if source_id is not None:
            query = query.where(FactItem.source_id == source_id)
        return list(self._session.scalars(query.order_by(FactItem.created_at, FactItem.id)))

    def confirm_item(self, item_id: UUID) -> FactItem:
        require_permission(self._context.role, Permission.MANAGE_FACTS)
        item = self._session.scalar(
            select(FactItem).where(
                FactItem.id == item_id,
                FactItem.workspace_id == self._context.workspace_id,
            )
        )
        if item is None:
            raise LookupError("fact item not found")
        if item.status is FactItemStatus.CONFIRMED:
            return item
        item.status = FactItemStatus.CONFIRMED
        item.confirmed_by = self._context.member_id
        item.confirmed_at = utc_now()
        self._session.add(
            AuditLog(
                workspace_id=self._context.workspace_id,
                action="fact_item.confirmed",
                resource_type="fact_item",
                resource_id=item.id,
                member_id=self._context.member_id,
                details={"source_id": str(item.source_id), "field": item.field_name},
            )
        )
        self._session.flush()
        return item

    def apply_extraction(
        self,
        source_id: UUID,
        *,
        text: str,
        parser_name: str,
    ) -> list[FactItem]:
        require_permission(self._context.role, Permission.MANAGE_FACTS)
        source = self.source(source_id)
        confirmed = self._session.scalar(
            select(FactItem.id).where(
                FactItem.workspace_id == self._context.workspace_id,
                FactItem.source_id == source_id,
                FactItem.status == FactItemStatus.CONFIRMED,
            )
        )
        if confirmed is not None:
            raise ValueError("confirmed fact items cannot be replaced by re-extraction")
        self._session.execute(
            delete(FactItem).where(
                FactItem.workspace_id == self._context.workspace_id,
                FactItem.source_id == source_id,
                FactItem.status == FactItemStatus.CANDIDATE,
            )
        )
        source.source_text = text
        source.status = FactSourceStatus.PARSED
        source.status_detail = {"parser": parser_name}
        return self._add_items(source, text)

    def apply_structured_extraction(
        self,
        source_id: UUID,
        *,
        candidates: list[tuple[str, str, str, float]],
        parser_name: str,
    ) -> list[FactItem]:
        require_permission(self._context.role, Permission.MANAGE_FACTS)
        source = self.source(source_id)
        if any(not 0 <= candidate[3] <= 1 for candidate in candidates):
            raise ValueError("fact extraction confidence must be between zero and one")
        confirmed = self._session.scalar(
            select(FactItem.id).where(
                FactItem.workspace_id == self._context.workspace_id,
                FactItem.source_id == source_id,
                FactItem.status == FactItemStatus.CONFIRMED,
            )
        )
        if confirmed is not None:
            raise ValueError("confirmed fact items cannot be replaced by re-extraction")
        self._session.execute(
            delete(FactItem).where(
                FactItem.workspace_id == self._context.workspace_id,
                FactItem.source_id == source_id,
                FactItem.status == FactItemStatus.CANDIDATE,
            )
        )
        source.status = FactSourceStatus.PARSED
        source.status_detail = {"parser": parser_name}
        return self._add_structured_items(source, candidates)

    def context(self) -> FactContext:
        require_permission(self._context.role, Permission.READ_CONTENT)
        sources = self.sources()
        items = self.items()
        confirmed = [item for item in items if item.status is FactItemStatus.CONFIRMED]
        candidates = [item for item in items if item.status is FactItemStatus.CANDIDATE]
        return {
            "unconstrained_facts": not confirmed,
            "has_sources": bool(sources),
            "requires_confirmation": bool(candidates),
            "confirmed_items": confirmed,
        }
