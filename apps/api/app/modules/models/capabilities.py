from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class Capability(StrEnum):
    TEXT = "text"
    VISION = "vision"
    IMAGE = "image"
    EMBEDDING = "embedding"


class AdapterStatus(StrEnum):
    VERIFIED = "verified"
    EXPERIMENTAL = "experimental"
    COMMUNITY = "community"
    INCOMPATIBLE = "incompatible"


class IncompatibleModelError(ValueError):
    pass


class ModelDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1, max_length=80)
    model_id: str = Field(min_length=1, max_length=160)
    capabilities: frozenset[Capability] = Field(min_length=1)
    status: AdapterStatus


StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)


@dataclass(frozen=True)
class ModelRequest(Generic[StructuredOutput]):
    capability: Capability
    prompt: str
    response_model: type[StructuredOutput]
    inputs: Mapping[str, object] = field(default_factory=dict)


def require_capabilities(
    descriptor: ModelDescriptor,
    required: Iterable[Capability],
) -> None:
    required_set = frozenset(required)
    if descriptor.status is AdapterStatus.INCOMPATIBLE:
        raise IncompatibleModelError(
            f"model {descriptor.model_id} is marked incompatible"
        )
    missing = required_set - descriptor.capabilities
    if missing:
        names = ", ".join(sorted(capability.value for capability in missing))
        raise IncompatibleModelError(
            f"model {descriptor.model_id} lacks capabilities: {names}"
        )


def select_compatible_model(
    descriptors: Iterable[ModelDescriptor],
    required: Iterable[Capability],
) -> ModelDescriptor:
    required_set = frozenset(required)
    priority = {
        AdapterStatus.VERIFIED: 0,
        AdapterStatus.EXPERIMENTAL: 1,
        AdapterStatus.COMMUNITY: 2,
        AdapterStatus.INCOMPATIBLE: 3,
    }
    compatible = [
        descriptor
        for descriptor in descriptors
        if descriptor.status is not AdapterStatus.INCOMPATIBLE
        and required_set <= descriptor.capabilities
    ]
    if not compatible:
        names = ", ".join(sorted(capability.value for capability in required_set))
        raise IncompatibleModelError(
            f"no compatible model provides capabilities: {names}"
        )
    return min(
        compatible,
        key=lambda descriptor: (
            priority[descriptor.status],
            descriptor.provider,
            descriptor.model_id,
        ),
    )
