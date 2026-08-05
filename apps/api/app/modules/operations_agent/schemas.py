from typing import Annotated
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
