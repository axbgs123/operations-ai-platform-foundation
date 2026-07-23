import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.modules.generation.cover_models import (
    CoverMode,
    CoverReference,
    CoverRequest,
    CoverSize,
    ReferencePurpose,
)
from app.modules.generation.layout import (
    CoverLayout,
    compute_cover_layout,
    render_cover,
)
from app.modules.models.capabilities import (
    AdapterStatus,
    Capability,
    IncompatibleModelError,
)


IMAGE_LAYER_POLICY = (
    "Only generate background and subject pixels. "
    "Do not render text, letters, logos, or brand marks."
)


class ImageModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy: str
    prompt: str
    size: CoverSize
    references: tuple[CoverReference, ...]
    locked_reference_ids: tuple[UUID, ...]
    allow_text: bool = False
    output_layers: tuple[str, ...] = ("background", "subject")
    parameters: dict[str, JsonValue] = Field(default_factory=dict)


class CoverPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: CoverMode
    prompt: str
    references: tuple[CoverReference, ...]
    uses_image_model: bool
    model_request: ImageModelRequest | None
    overlay_text: tuple[str, str]


class CoverImageAdapter(Protocol):
    capabilities: frozenset[Capability]
    status: AdapterStatus

    async def generate_layer(
        self,
        request: ImageModelRequest,
    ) -> Image.Image: ...


class MockCoverImageAdapter:
    capabilities = frozenset({Capability.IMAGE})
    status = AdapterStatus.VERIFIED

    async def generate_layer(
        self,
        request: ImageModelRequest,
    ) -> Image.Image:
        digest = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
        first = f"#{digest[:6]}"
        second = f"#{digest[6:12]}"
        image = Image.new(
            "RGB",
            (request.size.width, request.size.height),
            first,
        )
        draw = ImageDraw.Draw(image)
        draw.ellipse(
            (
                request.size.width // 5,
                request.size.height // 4,
                request.size.width,
                request.size.height,
            ),
            fill=second,
        )
        return image


@dataclass(frozen=True)
class CoverArtifact:
    png_bytes: bytes
    text_content: tuple[str, str, str]
    layout: CoverLayout
    mode: CoverMode
    logo_composited: bool


def build_cover_plan(request: CoverRequest) -> CoverPlan:
    uses_image_model = request.mode is not CoverMode.TEMPLATE
    locked_purposes: set[ReferencePurpose] = set()
    if request.preserve_person:
        locked_purposes.add(ReferencePurpose.PERSON)
    if request.preserve_product:
        locked_purposes.add(ReferencePurpose.PRODUCT)
    model_request = (
        ImageModelRequest(
            policy=IMAGE_LAYER_POLICY,
            prompt=request.prompt,
            size=request.size,
            references=request.references,
            locked_reference_ids=tuple(
                reference.asset_id
                for reference in request.references
                if reference.purpose in locked_purposes
            ),
            parameters=request.image_parameters,
        )
        if uses_image_model
        else None
    )
    return CoverPlan(
        mode=request.mode,
        prompt=request.prompt,
        references=request.references,
        uses_image_model=uses_image_model,
        model_request=model_request,
        overlay_text=(request.headline, request.subtitle),
    )


def _template_base(
    request: CoverRequest,
    asset_images: Mapping[UUID, Image.Image],
) -> Image.Image:
    composition = next(
        (
            asset_images[reference.asset_id]
            for reference in request.references
            if reference.purpose is ReferencePurpose.COMPOSITION
            and reference.asset_id in asset_images
        ),
        None,
    )
    if composition is not None:
        return composition
    image = Image.new(
        "RGB",
        (request.size.width, request.size.height),
        "#102a43",
    )
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        (
            0,
            request.size.height * 2 // 3,
            request.size.width,
            request.size.height,
        ),
        fill="#0b7285",
    )
    return image


async def generate_cover(
    request: CoverRequest,
    *,
    adapter: CoverImageAdapter | None = None,
    asset_images: Mapping[UUID, Image.Image] | None = None,
) -> CoverArtifact:
    images = asset_images or {}
    plan = build_cover_plan(request)
    if plan.model_request is None:
        base = _template_base(request, images)
    else:
        selected_adapter = adapter or MockCoverImageAdapter()
        if (
            selected_adapter.status is AdapterStatus.INCOMPATIBLE
            or Capability.IMAGE not in selected_adapter.capabilities
        ):
            raise IncompatibleModelError("cover adapter requires image capability")
        base = await selected_adapter.generate_layer(plan.model_request)
    logo = (
        images.get(request.logo_asset_id) if request.logo_asset_id is not None else None
    )
    if request.logo_asset_id is not None and logo is None:
        raise ValueError("selected logo asset is unavailable")
    layout = compute_cover_layout(
        size=request.size,
        headline=request.headline,
        subtitle=request.subtitle,
        brand_name=request.brand_name,
        safe_area=request.safe_area,
        logo_size=logo.size if logo is not None else None,
    )
    rendered = render_cover(base, layout, logo=logo)
    return CoverArtifact(
        png_bytes=rendered.png_bytes,
        text_content=rendered.text_content,
        layout=layout,
        mode=request.mode,
        logo_composited=logo is not None,
    )
