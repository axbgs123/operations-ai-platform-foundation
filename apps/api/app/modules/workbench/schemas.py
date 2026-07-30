from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


PlatformName = Literal["douyin", "xiaohongshu"]
AnalysisQueueStatus = Literal[
    "pending",
    "running",
    "completed",
    "insufficient_sample",
    "failed",
    "configuration_required",
    "suggestion_pending",
]
AnalysisQueueSort = Literal["newest", "oldest"]
PreflightQueueStatus = Literal[
    "pending_scan",
    "high_risk_blocked",
    "low_confidence_ocr",
    "no_active_rag_evidence",
    "modified_awaiting_rescan",
    "manually_confirmed",
    "review_required",
    "scan_failed",
]
PreflightQueueSort = Literal["newest", "oldest"]


class StrictReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkbenchAccountOption(StrictReadModel):
    account_id: UUID
    platform: PlatformName
    name: str = Field(min_length=1, max_length=120)


class WorkbenchContextRead(StrictReadModel):
    workspace_id: UUID
    workspace_name: str = Field(min_length=1, max_length=120)
    member_id: UUID
    member_display_name: str = Field(min_length=1, max_length=80)
    role: Literal["admin", "editor", "viewer"]
    accounts: list[WorkbenchAccountOption]
    failed_task_count: int = Field(ge=0)


class WorkbenchDataStatus(StrictReadModel):
    account_count: int = Field(ge=0)
    accounts_missing_recommended_snapshot: int = Field(ge=0)
    imports_waiting_confirmation: int = Field(ge=0)


class WorkbenchAttentionCounts(StrictReadModel):
    pending_analysis_count: int = Field(ge=0)
    high_risk_count: int = Field(ge=0)
    low_confidence_ocr_count: int = Field(ge=0)
    failed_task_count: int = Field(ge=0)


class WorkbenchNextAction(StrictReadModel):
    kind: Literal[
        "confirm_import",
        "review_analysis",
        "review_preflight",
    ]
    label: str = Field(min_length=1, max_length=120)
    href: str = Field(min_length=1, max_length=500)


class WorkbenchContentTypeCounts(StrictReadModel):
    video: int = Field(ge=0)
    image_text: int = Field(ge=0)


class WorkbenchCompleteness(StrictReadModel):
    score: float = Field(ge=0, le=1)
    missing_items: list[str]
    version: str = Field(min_length=1, max_length=80)


class WorkbenchAccountCard(StrictReadModel):
    account_id: UUID
    platform: PlatformName
    name: str = Field(min_length=1, max_length=120)
    content_type_counts: WorkbenchContentTypeCounts
    completeness: WorkbenchCompleteness
    pending_analysis_count: int = Field(ge=0)
    open_risk_count: int = Field(ge=0)
    has_current_week_closed_loop: bool
    confirmed_snapshot_count: int = Field(ge=0)
    latest_maturity_bucket: Literal["1h", "24h", "72h", "7d"] | None


class WorkbenchOverviewRead(StrictReadModel):
    data_status: WorkbenchDataStatus
    attention: WorkbenchAttentionCounts
    next_action: WorkbenchNextAction | None
    accounts: list[WorkbenchAccountCard]


class AnalysisQueueItem(StrictReadModel):
    content_id: UUID
    account_id: UUID
    account_name: str = Field(min_length=1, max_length=120)
    column_campaign_id: UUID | None
    column_campaign_name: str | None = Field(default=None, max_length=120)
    platform: PlatformName
    content_type: Literal["video", "image_text"]
    status: AnalysisQueueStatus
    maturity: Literal["1h", "24h", "72h", "7d"] | None
    sample_count: int = Field(ge=0, le=10_000)
    analysis_version: str | None = Field(default=None, max_length=160)
    safe_summary: str = Field(min_length=1, max_length=200)
    confidence: Literal["low", "medium", "high", "unknown"]
    evidence_status: Literal["available", "missing", "insufficient_sample"]
    suggestion_status: Literal["none", "saved", "adopted", "rejected"]


class AnalysisQueueRead(StrictReadModel):
    platform: PlatformName
    account_id: UUID | None
    status: AnalysisQueueStatus | None
    sort: AnalysisQueueSort
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    pages: int = Field(ge=0)
    items: list[AnalysisQueueItem]


class PreflightQueueItem(StrictReadModel):
    content_id: UUID
    account_id: UUID
    account_name: str = Field(min_length=1, max_length=120)
    column_campaign_id: UUID | None
    column_campaign_name: str | None = Field(default=None, max_length=120)
    platform: PlatformName
    content_type: Literal["video", "image_text"]
    lifecycle_status: str = Field(min_length=1, max_length=80)
    status: PreflightQueueStatus
    scan_id: UUID | None
    scan_node: Literal["after_ingestion", "after_generation", "before_publication"] | None
    finding_count: int = Field(ge=0, le=10_000)
    highest_severity: Literal["low", "medium", "high"] | None
    ocr_status: Literal[
        "not_run",
        "succeeded",
        "low_confidence",
        "failed",
        "unavailable",
    ]
    evidence_status: Literal["available", "no_active_evidence", "unavailable"]
    rule_version: str | None = Field(default=None, max_length=160)
    scan_version: str | None = Field(default=None, max_length=160)
    updated_at: datetime
    safe_summary: str = Field(min_length=1, max_length=200)
    next_action: str | None = Field(default=None, min_length=1, max_length=160)


class PreflightQueueRead(StrictReadModel):
    platform: PlatformName
    account_id: UUID | None
    status: PreflightQueueStatus | None
    sort: PreflightQueueSort
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    pages: int = Field(ge=0)
    items: list[PreflightQueueItem]
