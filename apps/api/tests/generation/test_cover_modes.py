import asyncio
from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image
from pydantic import ValidationError

from app.modules.generation.cover_models import (
    CoverMode,
    CoverReference,
    CoverRequest,
    CoverSize,
    ReferencePurpose,
)
from app.modules.generation.cover_service import (
    ImageModelRequest,
    build_cover_plan,
    generate_cover,
)
from app.modules.models.capabilities import (
    AdapterStatus,
    Capability,
    IncompatibleModelError,
)


class RecordingImageAdapter:
    capabilities = frozenset({Capability.IMAGE})
    status = AdapterStatus.VERIFIED

    def __init__(self) -> None:
        self.requests: list[ImageModelRequest] = []

    async def generate_layer(self, request: ImageModelRequest) -> Image.Image:
        self.requests.append(request)
        return Image.new(
            "RGB",
            (request.size.width, request.size.height),
            "#234766",
        )


class TextOnlyAdapter(RecordingImageAdapter):
    capabilities = frozenset({Capability.TEXT})


def _request(
    mode: CoverMode,
    *,
    references: tuple[CoverReference, ...] = (),
    preserve_person: bool = False,
    preserve_product: bool = False,
) -> CoverRequest:
    return CoverRequest(
        mode=mode,
        size=CoverSize(width=1080, height=1440),
        prompt="低饱和蓝色科技感，主体居中，顶部留白",
        headline="运营内容智能分析",
        subtitle="让每一条内容都有证据",
        references=references,
        preserve_person=preserve_person,
        preserve_product=preserve_product,
        model_config_id=(None if mode is CoverMode.TEMPLATE else uuid4()),
    )


@pytest.mark.parametrize("mode", list(CoverMode))
def test_all_four_cover_modes_keep_prompt_and_typed_references(
    mode: CoverMode,
) -> None:
    reference = CoverReference(
        asset_id=uuid4(),
        purpose=ReferencePurpose.COMPOSITION,
    )

    plan = build_cover_plan(_request(mode, references=(reference,)))

    assert plan.mode is mode
    assert plan.prompt == "低饱和蓝色科技感，主体居中，顶部留白"
    assert plan.references == (reference,)
    assert plan.uses_image_model is (mode is not CoverMode.TEMPLATE)


@pytest.mark.parametrize(
    "purpose",
    ["composition", "style", "person", "product", "palette"],
)
def test_reference_purpose_is_a_strict_five_value_enum(purpose: str) -> None:
    reference = CoverReference(asset_id=uuid4(), purpose=purpose)

    assert reference.purpose.value == purpose

    with pytest.raises(ValidationError):
        CoverReference(asset_id=uuid4(), purpose="logo")


@pytest.mark.parametrize(
    ("preserve_person", "preserve_product", "purpose"),
    [
        (True, False, ReferencePurpose.PERSON),
        (False, True, ReferencePurpose.PRODUCT),
    ],
)
def test_hybrid_mode_requires_matching_locked_subject_reference(
    preserve_person: bool,
    preserve_product: bool,
    purpose: ReferencePurpose,
) -> None:
    with pytest.raises(
        ValidationError,
        match="matching person or product reference",
    ):
        _request(
            CoverMode.HYBRID,
            preserve_person=preserve_person,
            preserve_product=preserve_product,
        )

    reference = CoverReference(asset_id=uuid4(), purpose=purpose)
    plan = build_cover_plan(
        _request(
            CoverMode.HYBRID,
            references=(reference,),
            preserve_person=preserve_person,
            preserve_product=preserve_product,
        )
    )

    assert plan.model_request is not None
    assert plan.model_request.locked_reference_ids == (reference.asset_id,)


@pytest.mark.parametrize(
    "mode",
    [CoverMode.AI_VISUAL, CoverMode.HYBRID, CoverMode.CUSTOM],
)
def test_image_model_only_receives_background_and_subject_instructions(
    mode: CoverMode,
) -> None:
    reference = CoverReference(
        asset_id=uuid4(),
        purpose=ReferencePurpose.PRODUCT,
    )
    request = _request(
        mode,
        references=(reference,),
        preserve_product=mode is CoverMode.HYBRID,
    )

    plan = build_cover_plan(request)

    assert plan.model_request is not None
    assert plan.model_request.allow_text is False
    assert plan.model_request.output_layers == ("background", "subject")
    assert request.headline not in plan.model_request.prompt
    assert request.subtitle not in plan.model_request.prompt
    assert plan.overlay_text == (request.headline, request.subtitle)


@pytest.mark.parametrize("mode", list(CoverMode))
def test_each_mode_produces_a_final_png_with_programmatic_text(
    mode: CoverMode,
) -> None:
    adapter = RecordingImageAdapter()
    request = _request(mode)

    artifact = asyncio.run(generate_cover(request, adapter=adapter))

    decoded = Image.open(BytesIO(artifact.png_bytes))
    assert decoded.size == (1080, 1440)
    assert artifact.text_content == (
        request.headline,
        request.subtitle,
        "示例品牌",
    )
    assert len(adapter.requests) == (0 if mode is CoverMode.TEMPLATE else 1)


def test_logo_is_composited_after_the_generated_visual_layer() -> None:
    logo_id = uuid4()
    request = _request(CoverMode.AI_VISUAL).model_copy(
        update={"logo_asset_id": logo_id}
    )
    adapter = RecordingImageAdapter()
    logo = Image.new("RGBA", (200, 80), "#ff3366")

    artifact = asyncio.run(
        generate_cover(
            request,
            adapter=adapter,
            asset_images={logo_id: logo},
        )
    )
    decoded = Image.open(BytesIO(artifact.png_bytes)).convert("RGB")

    assert artifact.logo_composited is True
    assert artifact.layout.logo is not None
    center = (
        artifact.layout.logo.x + artifact.layout.logo.width // 2,
        artifact.layout.logo.y + artifact.layout.logo.height // 2,
    )
    assert decoded.getpixel(center) == (255, 51, 102)


def test_custom_mode_passes_versionable_image_parameters() -> None:
    request = _request(CoverMode.CUSTOM).model_copy(
        update={
            "image_parameters": {
                "seed": 20260723,
                "guidance_scale": 6.5,
            }
        }
    )

    plan = build_cover_plan(request)

    assert plan.model_request is not None
    assert plan.model_request.parameters == {
        "seed": 20260723,
        "guidance_scale": 6.5,
    }


def test_cover_generation_rejects_adapter_without_image_capability() -> None:
    with pytest.raises(IncompatibleModelError, match="image capability"):
        asyncio.run(
            generate_cover(
                _request(CoverMode.AI_VISUAL),
                adapter=TextOnlyAdapter(),
            )
        )
