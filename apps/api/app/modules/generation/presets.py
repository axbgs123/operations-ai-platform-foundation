from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from app.core.database import utc_now, uuid7
from app.modules.generation.cover_models import (
    CoverSize,
    ReferencePurpose,
    SafeAreaSpec,
)


_SECRET_FIELD_NAMES = {
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "authorization",
    "client_secret",
    "provider_secret",
    "password",
    "secret",
    "token",
}
_SECRET_FIELD_SUFFIXES = (
    "_api_key",
    "_token",
    "_secret",
    "_password",
)


def _normalized_key(value: object) -> str:
    return str(value).strip().lower().replace("-", "_")


def _assert_secret_free(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = _normalized_key(key)
            if normalized in _SECRET_FIELD_NAMES or normalized.endswith(
                _SECRET_FIELD_SUFFIXES
            ):
                raise ValueError("generation preset must not contain secrets")
            _assert_secret_free(item)
    elif isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        for item in value:
            _assert_secret_free(item)


class ImmutablePresetModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BrandElements(ImmutablePresetModel):
    brand_name: str = Field(min_length=1, max_length=120)
    logo_asset_id: UUID | None = None
    primary_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class GenerationPreset(ImmutablePresetModel):
    id: UUID = Field(default_factory=uuid7)
    name: str = Field(min_length=1, max_length=160)
    model_config_id: UUID
    size: CoverSize
    image_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    reference_purposes: tuple[ReferencePurpose, ...] = ()
    text_area: SafeAreaSpec = Field(default_factory=SafeAreaSpec)
    brand: BrandElements
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("name")
    @classmethod
    def require_nonblank_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("preset name must not be blank")
        return normalized

    @field_validator("image_parameters")
    @classmethod
    def reject_secret_parameters(
        cls,
        value: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        _assert_secret_free(value)
        return value

    @model_validator(mode="after")
    def require_unique_reference_purposes(self) -> Self:
        if len(self.reference_purposes) != len(set(self.reference_purposes)):
            raise ValueError("reference purposes must be unique")
        return self

    def persisted_payload(self) -> dict[str, JsonValue]:
        validated = type(self).model_validate(self.model_dump(mode="python"))
        return validated.model_dump(mode="json")


def revise_generation_preset(
    preset: GenerationPreset,
    *,
    image_parameters: dict[str, JsonValue] | None = None,
    text_area: SafeAreaSpec | None = None,
    brand: BrandElements | None = None,
) -> GenerationPreset:
    payload = preset.model_dump(mode="python")
    payload.update(
        {
            "image_parameters": (
                image_parameters
                if image_parameters is not None
                else preset.image_parameters
            ),
            "text_area": text_area or preset.text_area,
            "brand": brand or preset.brand,
            "version": preset.version + 1,
            "created_at": utc_now(),
        }
    )
    return GenerationPreset.model_validate(payload)
