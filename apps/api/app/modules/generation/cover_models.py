from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class CoverMode(StrEnum):
    TEMPLATE = "template"
    AI_VISUAL = "ai_visual"
    HYBRID = "hybrid"
    CUSTOM = "custom"


class ReferencePurpose(StrEnum):
    COMPOSITION = "composition"
    STYLE = "style"
    PERSON = "person"
    PRODUCT = "product"
    PALETTE = "palette"


class CoverSize(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    width: int = Field(ge=256, le=4096)
    height: int = Field(ge=256, le=4096)


class SafeAreaSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: float = Field(default=0.08, ge=0, lt=1)
    y: float = Field(default=0.08, ge=0, lt=1)
    width: float = Field(default=0.84, gt=0, le=1)
    height: float = Field(default=0.84, gt=0, le=1)

    @model_validator(mode="after")
    def require_inside_canvas(self) -> "SafeAreaSpec":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("safe area must stay within the canvas")
        return self


class CoverReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_id: UUID
    purpose: ReferencePurpose
    provider_input: bool = True


class CoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: CoverMode
    size: CoverSize
    prompt: str = Field(min_length=1, max_length=20_000)
    headline: str = Field(min_length=1, max_length=200)
    subtitle: str = Field(default="", max_length=400)
    references: tuple[CoverReference, ...] = Field(default=(), max_length=12)
    preserve_person: bool = False
    preserve_product: bool = False
    model_config_id: UUID | None = None
    safe_area: SafeAreaSpec = Field(default_factory=SafeAreaSpec)
    brand_name: str = Field(default="示例品牌", min_length=1, max_length=120)
    logo_asset_id: UUID | None = None
    image_parameters: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_mode_requirements(self) -> "CoverRequest":
        if self.mode is not CoverMode.TEMPLATE and self.model_config_id is None:
            raise ValueError("image model config is required for this cover mode")
        provider_references = tuple(
            reference
            for reference in self.references
            if reference.provider_input
        )
        if len(provider_references) > 3:
            raise ValueError(
                "at most three references may be sent to the image provider"
            )
        purposes = {
            reference.purpose for reference in provider_references
        }
        if self.mode is CoverMode.HYBRID and (
            (self.preserve_person and ReferencePurpose.PERSON not in purposes)
            or (self.preserve_product and ReferencePurpose.PRODUCT not in purposes)
        ):
            raise ValueError(
                "hybrid preservation requires matching person or product reference"
            )
        if len({reference.asset_id for reference in self.references}) != len(
            self.references
        ):
            raise ValueError("reference assets must be unique")
        if self.mode is not CoverMode.CUSTOM and self.image_parameters:
            raise ValueError(
                "image parameters are only supported in custom mode"
            )
        if set(self.image_parameters) - {"seed", "negative_prompt"}:
            raise ValueError(
                "custom image parameters must use the server allowlist"
            )
        return self
