from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, Field, model_validator


class ContentCreate(BaseModel):
    workspace_id: UUID
    account_id: UUID
    platform: Literal["douyin", "xiaohongshu"]
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(max_length=100_000)
    column_campaign_id: UUID | None = None
    work_url: AnyHttpUrl | None = None


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
