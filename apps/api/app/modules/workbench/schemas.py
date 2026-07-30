from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


PlatformName = Literal["douyin", "xiaohongshu"]


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
    platform: PlatformName
    content_type: Literal["video", "image_text"]
    status: Literal["not_analyzed", "queued", "running", "failed"]
    snapshot_count: int = Field(ge=0, le=10_000)
    analysis_version: str | None = Field(default=None, max_length=160)
    safe_summary: str = Field(min_length=1, max_length=200)


class AnalysisQueueRead(StrictReadModel):
    platform: PlatformName
    account_id: UUID | None
    total: int = Field(ge=0)
    items: list[AnalysisQueueItem]


class PreflightQueueItem(StrictReadModel):
    content_id: UUID
    account_id: UUID
    platform: PlatformName
    content_type: Literal["video", "image_text"]
    status: Literal[
        "not_scanned",
        "scan_pending",
        "high_risk",
        "review_required",
        "clear",
        "scan_failed",
    ]
    scan_id: UUID | None
    finding_count: int = Field(ge=0, le=10_000)
    scan_version: str | None = Field(default=None, max_length=160)
    safe_summary: str = Field(min_length=1, max_length=200)


class PreflightQueueRead(StrictReadModel):
    platform: PlatformName
    account_id: UUID | None
    total: int = Field(ge=0)
    items: list[PreflightQueueItem]
