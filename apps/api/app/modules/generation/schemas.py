from datetime import datetime
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.core.database import utc_now, uuid7
from app.modules.content.account_models import Platform


class ImmutableSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StyleInheritanceSelection(ImmutableSchema):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    title: bool = True
    copy_style: bool = Field(default=True, alias="copy")
    cover: bool = True


class GenerationInputs(ImmutableSchema):
    account_id: UUID
    platform: Platform
    column_campaign_id: UUID | None = None
    target: str = Field(min_length=1, max_length=160)
    confirmed_fact_item_ids: tuple[UUID, ...] = ()
    style_profile_id: UUID | None = None
    style_switches: StyleInheritanceSelection = Field(
        default_factory=StyleInheritanceSelection
    )
    viral_library_item_ids: tuple[UUID, ...] = Field(
        default=(),
        max_length=3,
    )
    user_prompt: str = Field(default="", max_length=20_000)
    source_asset_ids: tuple[UUID, ...] = ()
    risk_rule_version: str = Field(min_length=1, max_length=160)
    model_config_id: UUID

    @field_validator("target", "risk_rule_version")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @model_validator(mode="after")
    def require_unique_references(self) -> "GenerationInputs":
        for label, values in (
            ("confirmed fact item ids", self.confirmed_fact_item_ids),
            ("viral library item ids", self.viral_library_item_ids),
            ("source asset ids", self.source_asset_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must be unique")
        return self


class ConfirmedFactSnapshot(ImmutableSchema):
    item_id: UUID
    field_code: str
    value: str
    source_id: UUID
    source_level: str


class StyleSnapshot(ImmutableSchema):
    profile_id: UUID
    version: int
    switches: StyleInheritanceSelection
    style_json: str


class ViralReferenceSnapshot(ImmutableSchema):
    library_item_id: UUID
    content_id: UUID
    category: str
    strategy_tags: tuple[str, ...]
    applicable_scenarios: tuple[str, ...]
    structure_summary: str


class ModelSnapshot(ImmutableSchema):
    config_id: UUID
    provider: str
    model_id: str
    capabilities: tuple[str, ...]
    status: str


class SourceAssetSnapshot(ImmutableSchema):
    source_id: UUID
    kind: str
    content_sha256: str
    status: str
    file_name: str | None
    mime_type: str | None
    source_url: str | None


class GenerationContext(ImmutableSchema):
    id: UUID = Field(default_factory=uuid7)
    workspace_id: UUID
    account_id: UUID
    platform: Platform
    column_campaign_id: UUID | None
    target: str
    confirmed_facts: tuple[ConfirmedFactSnapshot, ...]
    confirmed_facts_version: str
    style: StyleSnapshot | None
    viral_references: tuple[ViralReferenceSnapshot, ...]
    user_prompt: str
    source_assets: tuple[SourceAssetSnapshot, ...]
    risk_rule_version: str
    model: ModelSnapshot
    created_at: datetime = Field(default_factory=utc_now)


class GenerationRun(ImmutableSchema):
    id: UUID = Field(default_factory=uuid7)
    context: GenerationContext
    retry_of_run_id: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)
