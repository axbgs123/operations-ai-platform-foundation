from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator

from app.modules.analysis.schemas import AnalysisRunRead
from app.modules.metrics.schemas import SnapshotRead
from app.modules.risk_rag.scanner import RiskScanOutput


class ContentCreate(BaseModel):
    workspace_id: UUID
    account_id: UUID
    platform: Literal["douyin", "xiaohongshu"]
    content_type: Literal["video", "image_text"] = "video"
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(max_length=100_000)
    column_campaign_id: UUID | None = None
    work_url: AnyHttpUrl | None = None
    platform_content_id: str | None = Field(default=None, max_length=255)


class ContentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    body: str | None = Field(default=None, max_length=100_000)
    column_campaign_id: UUID | None = None
    work_url: AnyHttpUrl | None = None
    status: Literal["published", "archived"] | None = None
    restore: Literal[True] | None = None

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one change is required")
        if self.restore and len(self.model_fields_set) != 1:
            raise ValueError("restore cannot be combined with other changes")
        return self


class AssetPresignRequest(BaseModel):
    category: Literal["cover", "screenshot", "reference_image", "document"]
    file_name: str = Field(min_length=1, max_length=255)
    mime_type: Literal[
        "image/jpeg",
        "image/png",
        "image/webp",
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
    ]
    size: int = Field(gt=0, le=20 * 1024 * 1024)

    @model_validator(mode="after")
    def validate_category_limits(self) -> Self:
        if self.category != "document" and not self.mime_type.startswith("image/"):
            raise ValueError("image asset requires image MIME type")
        if self.category != "document" and self.size > 10 * 1024 * 1024:
            raise ValueError("image assets are limited to 10 MiB")
        return self


class AssetConfirmRequest(BaseModel):
    upload_token: str = Field(min_length=20, max_length=4096)


class AssetRead(BaseModel):
    id: UUID
    category: Literal["cover", "screenshot", "reference_image", "document"]
    file_name: str
    mime_type: str
    size: int
    download_url: str | None = None
    download_url_expires_at: datetime | None = None


class ContentRead(BaseModel):
    id: UUID
    workspace_id: UUID
    account_id: UUID
    account_name: str
    platform: Literal["douyin", "xiaohongshu"]
    content_type: Literal["video", "image_text"]
    title: str
    body: str
    status: Literal["draft", "published", "archived"]
    column_campaign_id: UUID | None
    column_campaign_name: str | None
    work_url: str | None
    platform_content_id: str | None
    published_title: str | None
    published_body: str | None
    published_at: datetime | None
    deleted_at: datetime | None
    objective_profile_id: UUID
    benchmark_profile_id: UUID
    assets: list[AssetRead]


class StrictContentReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContentListItemRead(StrictContentReadModel):
    id: UUID
    title: str
    platform: Literal["douyin", "xiaohongshu"]
    account_id: UUID
    account_name: str
    column_campaign_id: UUID | None
    column_campaign_name: str | None
    content_type: Literal["video", "image_text"]
    lifecycle_status: Literal["draft", "published", "archived"]
    published_at: datetime | None
    latest_maturity: Literal["1h", "24h", "72h", "7d"] | None
    data_completeness: float = Field(ge=0, le=1)
    analysis_status: Literal[
        "not_requested",
        "pending",
        "running",
        "succeeded",
        "failed",
    ]
    risk_status: Literal[
        "not_scanned",
        "pending",
        "clear",
        "low",
        "medium",
        "high",
        "failed",
    ]
    cover: AssetRead | None


class ContentListPageRead(StrictContentReadModel):
    items: list[ContentListItemRead]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    pages: int = Field(ge=0)


class ContentRiskRecordRead(StrictContentReadModel):
    id: UUID
    previous_scan_id: UUID | None
    status: Literal[
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancelled",
        "retrying",
    ]
    node: Literal["after_ingestion", "after_generation", "before_publication"]
    result: RiskScanOutput | None
    error_code: str | None
    diagnostics: list[str]
    rule_version: str
    evidence_version: str
    embedding_model_id: str
    embedding_version: str
    rag_model_version: str
    scanner_version: str
    ocr_provider: str
    ocr_model_id: str
    created_at: datetime


class ContentGenerationRecordRead(StrictContentReadModel):
    id: UUID
    kind: Literal["cover"]
    status: str
    provider: str
    model_id: str
    contract_version: str
    account_style_version: str | None
    column_override_version: str | None
    confirmed_facts_version: str | None
    viral_reference_count: int | None
    preset_version: str | None
    original_result: str | None
    final_result: str | None
    adoption_status: str | None
    modification_magnitude: float | None
    created_at: datetime
    completed_at: datetime | None


class ContentSnapshotTrendPointRead(StrictContentReadModel):
    snapshot_id: UUID
    collected_at: datetime
    normalized_value: str


class ContentSnapshotTrendRead(StrictContentReadModel):
    eligible: bool
    reason: str
    metric_key: str | None
    points: list[ContentSnapshotTrendPointRead]


class ContentDetailRead(StrictContentReadModel):
    content: ContentRead
    lifecycle_stage: Literal[
        "灵感/选题",
        "AI生成",
        "人工编辑",
        "待审核",
        "已发布",
        "数据采集中",
        "已分析",
        "可复用",
        "未知",
    ]
    snapshots: list[SnapshotRead]
    snapshot_trend: ContentSnapshotTrendRead
    analysis_runs: list[AnalysisRunRead]
    risk_scans: list[ContentRiskRecordRead]
    generation_records: list[ContentGenerationRecordRead]


class AssetUploadGrantRead(BaseModel):
    object_key: str
    upload_url: str
    upload_headers: dict[str, str]
    upload_token: str
    expires_at: datetime
