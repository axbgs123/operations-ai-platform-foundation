from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.generation.cover_models import (
    CoverSize,
    ReferencePurpose,
    SafeAreaSpec,
)
from app.modules.generation.presets import (
    BrandElements,
    GenerationPreset,
    revise_generation_preset,
)


def preset() -> GenerationPreset:
    return GenerationPreset(
        name="小红书服装首图",
        model_config_id=uuid4(),
        size=CoverSize(width=1080, height=1440),
        image_parameters={"seed": 20260723, "guidance_scale": 6.5},
        reference_purposes=(
            ReferencePurpose.PRODUCT,
            ReferencePurpose.PALETTE,
        ),
        text_area=SafeAreaSpec(x=0.08, y=0.08, width=0.84, height=0.52),
        brand=BrandElements(
            brand_name="示例品牌",
            logo_asset_id=uuid4(),
            primary_color="#102a43",
        ),
        version=1,
    )


def test_preset_persists_governed_generation_configuration() -> None:
    saved = preset()

    payload = saved.persisted_payload()

    assert payload["model_config_id"] == str(saved.model_config_id)
    assert payload["size"] == {"width": 1080, "height": 1440}
    assert payload["image_parameters"] == {
        "seed": 20260723,
        "guidance_scale": 6.5,
    }
    assert payload["reference_purposes"] == ["product", "palette"]
    assert payload["text_area"]["height"] == 0.52
    assert payload["brand"]["brand_name"] == "示例品牌"
    assert payload["version"] == 1


@pytest.mark.parametrize(
    "parameters",
    [
        {"api_key": "sk-not-real"},
        {"nested": {"access_token": "not-real"}},
        {"authorization": "Bearer not-real"},
        {"provider": {"openai_api_key": "not-real"}},
        {"provider": {"bearer_token": "not-real"}},
    ],
)
def test_preset_rejects_secret_material_at_any_parameter_depth(
    parameters: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="must not contain secrets"):
        preset().model_copy(update={"image_parameters": parameters}).persisted_payload()


def test_preset_schema_forbids_top_level_provider_secret() -> None:
    with pytest.raises(ValidationError):
        GenerationPreset.model_validate(
            {
                **preset().model_dump(mode="json"),
                "provider_secret": "not-real",
            }
        )


def test_revising_preset_keeps_identity_and_increments_version() -> None:
    original = preset()

    revised = revise_generation_preset(
        original,
        image_parameters={"seed": 7},
        text_area=SafeAreaSpec(x=0.1, y=0.1, width=0.8, height=0.5),
    )

    assert revised.id == original.id
    assert revised.version == 2
    assert revised.image_parameters == {"seed": 7}
    assert revised.text_area.height == 0.5
    assert original.version == 1
    assert original.image_parameters["seed"] == 20260723


def test_reference_purposes_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="must be unique"):
        preset().model_copy(
            update={
                "reference_purposes": (
                    ReferencePurpose.STYLE,
                    ReferencePurpose.STYLE,
                )
            }
        ).persisted_payload()
