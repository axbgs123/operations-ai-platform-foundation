from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.content.account_models import Platform
from app.modules.risk_rag.models import (
    RiskAuthorizationStatus,
    RiskDocumentScope,
    RiskDocumentStatus,
    RiskSourceLevel,
)


class RiskDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID | None
    platform: Platform
    scope: RiskDocumentScope
    source_level: RiskSourceLevel
    title: str
    source_url: str | None
    private_document_id: str | None
    published_at: datetime | None
    effective_at: datetime | None
    accessed_at: datetime | None
    authorization_status: RiskAuthorizationStatus
    reviewed_by: UUID | None
    previous_version_id: UUID | None
    version: int
    status: RiskDocumentStatus
    created_at: datetime
    updated_at: datetime


class RiskDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Platform
    source_level: RiskSourceLevel
    title: str = Field(min_length=1, max_length=300)
    private_document_id: str = Field(min_length=1, max_length=255)
    authorization_status: RiskAuthorizationStatus
    published_at: datetime | None = None
    effective_at: datetime | None = None
    accessed_at: datetime | None = None


class RiskDocumentTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: RiskDocumentStatus


class RiskChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID | None
    document_id: UUID
    platform: Platform
    scope: RiskDocumentScope
    chunk_index: int
    source_location: str
    text: str
    metadata_json: dict[str, object]
