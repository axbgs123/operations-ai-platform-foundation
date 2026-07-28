from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ManualPreviewRequest(BaseModel):
    account_id: UUID
    platform: Literal["douyin", "xiaohongshu"]
    content_type: Literal["video", "image_text"]
    rows: list[dict[str, object]] = Field(min_length=1, max_length=1000)


class HeaderMappingUpdate(BaseModel):
    mapping: dict[str, str] = Field(min_length=1, max_length=100)


class ImportRowUpdate(BaseModel):
    changes: dict[str, object] = Field(min_length=1, max_length=100)
    selected: bool | None = None


class ImportConfirmRequest(BaseModel):
    selected_row_ids: list[UUID] = Field(min_length=1, max_length=1000)


class HeaderMappingRead(BaseModel):
    source_header: str
    target_field: str | None
    confidence: float
    high_confidence: bool


class ImportErrorRead(BaseModel):
    field: str
    message: str


class ImportRowRead(BaseModel):
    id: UUID
    row_number: int
    status: Literal["new", "update", "suspected_duplicate", "failed"]
    selected: bool
    raw_data: dict[str, object]
    normalized_data: dict[str, object]
    errors: list[ImportErrorRead]
    matched_content_id: UUID | None
    dedupe_reason: str | None


class ImportSummaryRead(BaseModel):
    new: int
    update: int
    suspected_duplicate: int
    failed: int


class ImportBatchRead(BaseModel):
    id: UUID
    workspace_id: UUID
    account_id: UUID
    platform: Literal["douyin", "xiaohongshu"]
    content_type: Literal["video", "image_text"]
    source_kind: Literal["manual", "csv", "xlsx", "screenshot"]
    status: Literal["preview", "confirmed"]
    recognition_status: Literal["pending", "processing", "ready", "failed"] | None
    recognition_error: str | None
    provider_mode: str
    region: str | None
    file_name: str | None
    header_mappings: list[HeaderMappingRead]
    rows: list[ImportRowRead]
    summary: ImportSummaryRead


class ImportConfirmationRead(BaseModel):
    batch_id: UUID
    content_ids: list[UUID]
    snapshot_ids: list[UUID]
    skipped_row_ids: list[UUID]
