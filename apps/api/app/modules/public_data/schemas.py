from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr

from app.modules.content.account_models import Platform


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderConfigInput(StrictModel):
    api_key: SecretStr
    endpoint_region: Literal["china", "global"] = "china"
    daily_request_limit: int = Field(default=500, ge=1, le=100_000)


class ProviderConfigRead(StrictModel):
    id: UUID
    provider: Literal["tikhub"]
    endpoint_region: Literal["china", "global"]
    status: Literal["unverified", "verified", "disabled"]
    daily_request_limit: int
    daily_requests_used: int
    configuration_revision: int
    last_tested_at: datetime | None
    safe_error_code: str | None
    has_api_key: Literal[True] = True


class ProviderConnectionRead(StrictModel):
    connected: bool
    status: Literal["verified", "failed"]
    checked_at: datetime
    safe_error_code: str | None


class ContentBindingInput(StrictModel):
    public_url: AnyHttpUrl
    published_at: datetime
    platform_content_id: str | None = Field(default=None, min_length=3, max_length=255)


class CollectionJobRead(StrictModel):
    id: UUID
    target_window: str
    due_at: datetime
    next_attempt_at: datetime
    status: Literal[
        "scheduled", "running", "retrying", "succeeded", "failed", "cancelled"
    ]
    attempt_count: int
    snapshot_id: UUID | None
    safe_error_code: str | None


class ContentBindingRead(StrictModel):
    id: UUID
    content_id: UUID
    account_id: UUID
    platform: Literal["douyin", "xiaohongshu"]
    public_url: str
    platform_content_id: str
    published_at: datetime
    status: Literal["active", "error", "disabled"]
    last_verified_at: datetime | None
    safe_error_code: str | None
    jobs: list[CollectionJobRead]


class CompetitorAccountInput(StrictModel):
    platform: Platform
    name: str = Field(min_length=1, max_length=160)
    public_url: AnyHttpUrl
    platform_account_id: str | None = Field(default=None, min_length=3, max_length=255)
    collection_interval_hours: int = Field(default=24, ge=6, le=168)


class CompetitorPostRead(StrictModel):
    content_id: str
    public_url: str | None = None
    title: str
    published_at: str | int | float | None
    views: int | float | None
    likes: int | float | None
    comments: int | float | None
    favorites: int | float | None
    shares: int | float | None


class CompetitorAccountRead(StrictModel):
    id: UUID
    platform: Literal["douyin", "xiaohongshu"]
    name: str
    public_url: str
    platform_account_id: str
    status: Literal["active", "error", "disabled"]
    collection_interval_hours: int
    next_collection_at: datetime
    last_collected_at: datetime | None
    safe_error_code: str | None
    follower_count: int | None
    latest_posts: list[CompetitorPostRead]


class CommentDemandInput(StrictModel):
    platform: Platform
    public_url: AnyHttpUrl
    platform_content_id: str | None = Field(default=None, min_length=3, max_length=255)


class CommentDemandThemeRead(StrictModel):
    theme: str
    count: int
    examples: list[str]


class CommentDemandRead(StrictModel):
    id: UUID
    platform: Literal["douyin", "xiaohongshu"]
    public_url: str
    platform_content_id: str
    provider: str
    collected_at: datetime
    comment_count: int
    themes: list[CommentDemandThemeRead]
    top_questions: list[str]


class PublicTrendSearchInput(StrictModel):
    platform: Platform
    keyword: str = Field(min_length=2, max_length=120)


class PublicTrendSearchRead(StrictModel):
    id: UUID
    platform: Literal["douyin", "xiaohongshu"]
    keyword: str
    provider: str
    collected_at: datetime
    results: list[CompetitorPostRead]


class OperationsAlertRead(StrictModel):
    kind: Literal["competitor_viral", "own_growth"]
    platform: Literal["douyin", "xiaohongshu"]
    title: str
    detail: str
    public_url: str | None


class PublicOperationsReportRead(StrictModel):
    generated_at: datetime
    own_updates_24h: int
    monitored_accounts: int
    comment_analyses_24h: int
    alerts: list[OperationsAlertRead]
    actions: list[str]
