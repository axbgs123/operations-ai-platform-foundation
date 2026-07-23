from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.content.account_models import Platform
from app.modules.risk_rag.models import (
    RiskFeedbackStatus,
    RiskFeedbackType,
    RiskAuthorizationStatus,
    RiskDocumentScope,
    RiskDocumentStatus,
    RiskSourceLevel,
    RiskScanNode,
    RiskScanStatus,
)
from app.modules.risk_rag.scanner import RiskScanOutput


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


class RiskScanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    account_id: UUID
    content_id: UUID
    cover_asset_id: UUID | None
    previous_scan_id: UUID | None
    platform: Platform
    node: RiskScanNode
    status: RiskScanStatus
    idempotency_key: str
    input_snapshot: dict[str, object]
    result: RiskScanOutput | None
    error_code: str | None
    diagnostics: list[str]
    rule_version: str
    evidence_version: str
    embedding_model_id: str
    embedding_version: str
    embedding_dimension: int
    rag_model_version: str
    scanner_version: str
    created_at: datetime


class RiskFeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    scan_id: UUID
    platform: Platform
    feedback_type: RiskFeedbackType
    status: RiskFeedbackStatus
    finding_reference: str
    rule_version: str
    evidence_version: str
    submitted_by: UUID | None
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    created_at: datetime
