from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)

from app.modules.content.account_models import Platform


Fingerprint = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class CandidateKind(StrEnum):
    HIGH_RISK_BLOCKED = "high_risk_blocked"
    LOW_CONFIDENCE_OCR = "low_confidence_ocr"
    NO_ACTIVE_RAG_EVIDENCE = "no_active_rag_evidence"
    PREFLIGHT_REVIEW_REQUIRED = "preflight_review_required"
    CONFIGURATION_REQUIRED = "configuration_required"
    PERMISSION_SECURITY_FAILURE = "permission_security_failure"
    FAILED_TASK = "failed_task"
    IMPORT_WAITING_CONFIRMATION = "import_waiting_confirmation"
    PENDING_ANALYSIS = "pending_analysis"
    INCOMPLETE_DATA = "incomplete_data"


class BriefingCandidateRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: CandidateKind
    platform: Platform
    account_id: UUID
    content_id: UUID | None = None
    is_primary: bool
    safe_title: str = Field(min_length=1, max_length=160)
    safe_reason: str = Field(min_length=1, max_length=300)
    blocking_rank: int = Field(ge=0, le=10)
    severity_rank: int = Field(ge=0, le=10)
    evidence_rank: int = Field(ge=0, le=10)
    objective_rank: int = Field(ge=0, le=10)
    executable_rank: int = Field(ge=0, le=10)
    repeat_penalty: int = Field(ge=0, le=10_000)
    evidence_refs: tuple[str, ...] = Field(max_length=20)


class DailyBriefingRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    workspace_id: UUID
    input_fingerprint: Fingerprint
    algorithm_version: str = Field(min_length=1, max_length=80)
    tool_catalog_version: str = Field(min_length=1, max_length=80)
    data_cutoff_at: datetime
    primary: BriefingCandidateRead | None
    candidates: tuple[BriefingCandidateRead, ...]
    created_at: datetime


class BriefingDecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Literal["defer", "suppress_kind"]
    candidate_kind: CandidateKind | None = None

    @model_validator(mode="after")
    def validate_candidate_kind(self) -> "BriefingDecisionCreate":
        if self.decision == "suppress_kind" and self.candidate_kind is None:
            raise ValueError("candidate_kind is required for suppress_kind")
        if self.decision == "defer" and self.candidate_kind is not None:
            raise ValueError("candidate_kind must be omitted for defer")
        return self


class AgentPlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step_index: int = Field(ge=0)
    tool_name: str = Field(min_length=1, max_length=80)
    tool_version: str = Field(min_length=1, max_length=40)
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    rationale: str = Field(min_length=1, max_length=500)


class AgentPlanDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    goal: str = Field(min_length=1, max_length=500)
    platform: Platform
    account_id: UUID
    candidate_id: str = Field(min_length=1, max_length=120)
    input_fingerprint: Fingerprint
    tool_catalog_version: str = Field(min_length=1, max_length=80)
    steps: tuple[AgentPlanStep, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def require_unique_ordered_step_indexes(self) -> "AgentPlanDocument":
        indexes = [step.step_index for step in self.steps]
        if len(indexes) != len(set(indexes)):
            raise ValueError("step indexes must be unique")
        if indexes != list(range(len(indexes))):
            raise ValueError("step indexes must be contiguous and start at zero")
        return self
