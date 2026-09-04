from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr


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
