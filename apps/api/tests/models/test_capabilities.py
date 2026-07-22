from pydantic import BaseModel
import pytest

from app.modules.models.capabilities import (
    AdapterStatus,
    Capability,
    IncompatibleModelError,
    ModelDescriptor,
    ModelRequest,
    require_capabilities,
    select_compatible_model,
)


class StructuredText(BaseModel):
    content: str


def test_all_required_model_capabilities_are_explicit() -> None:
    assert set(Capability) == {
        Capability.TEXT,
        Capability.VISION,
        Capability.IMAGE,
        Capability.EMBEDDING,
    }


def test_model_request_binds_a_capability_and_response_schema() -> None:
    request = ModelRequest(
        capability=Capability.TEXT,
        prompt="总结这条合成内容",
        response_model=StructuredText,
        inputs={"content_id": "synthetic-1"},
    )

    assert request.capability is Capability.TEXT
    assert request.response_model is StructuredText


def test_capability_match_rejects_missing_and_incompatible_adapters() -> None:
    text_only = ModelDescriptor(
        provider="contract",
        model_id="text-only",
        capabilities=frozenset({Capability.TEXT}),
        status=AdapterStatus.VERIFIED,
    )
    incompatible = ModelDescriptor(
        provider="contract",
        model_id="disabled",
        capabilities=frozenset(Capability),
        status=AdapterStatus.INCOMPATIBLE,
    )

    require_capabilities(text_only, {Capability.TEXT})
    with pytest.raises(IncompatibleModelError, match="vision"):
        require_capabilities(text_only, {Capability.VISION})
    with pytest.raises(IncompatibleModelError, match="incompatible"):
        require_capabilities(incompatible, {Capability.TEXT})


def test_selection_prefers_verified_then_experimental_then_community() -> None:
    descriptors = [
        ModelDescriptor(
            provider="community-provider",
            model_id="community-vision",
            capabilities=frozenset({Capability.VISION}),
            status=AdapterStatus.COMMUNITY,
        ),
        ModelDescriptor(
            provider="experimental-provider",
            model_id="experimental-vision",
            capabilities=frozenset({Capability.VISION}),
            status=AdapterStatus.EXPERIMENTAL,
        ),
        ModelDescriptor(
            provider="verified-provider",
            model_id="verified-vision",
            capabilities=frozenset({Capability.VISION, Capability.TEXT}),
            status=AdapterStatus.VERIFIED,
        ),
    ]

    selected = select_compatible_model(descriptors, {Capability.VISION})

    assert selected.model_id == "verified-vision"


def test_selection_rejects_when_no_model_has_every_required_capability() -> None:
    descriptors = [
        ModelDescriptor(
            provider="contract",
            model_id="text-only",
            capabilities=frozenset({Capability.TEXT}),
            status=AdapterStatus.VERIFIED,
        ),
        ModelDescriptor(
            provider="contract",
            model_id="vision-only",
            capabilities=frozenset({Capability.VISION}),
            status=AdapterStatus.VERIFIED,
        ),
    ]

    with pytest.raises(IncompatibleModelError, match="text, vision"):
        select_compatible_model(
            descriptors,
            {Capability.TEXT, Capability.VISION},
        )
