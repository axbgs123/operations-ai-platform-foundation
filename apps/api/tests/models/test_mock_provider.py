import asyncio
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
import pytest

from app.modules.models.adapters.mock import MockProvider
from app.modules.models.capabilities import (
    AdapterStatus,
    Capability,
    IncompatibleModelError,
    ModelRequest,
)


class MockTextResult(BaseModel):
    content: str
    fingerprint: str


class MockEmbeddingResult(BaseModel):
    vector: list[float]
    fingerprint: str


class MockCapabilityResult(BaseModel):
    kind: Literal["mock"]
    label: str
    fingerprint: str


class MockTone(StrEnum):
    NEUTRAL = "neutral"
    LIVELY = "lively"


class MockRichResult(BaseModel):
    id: UUID
    tone: MockTone
    confidence: float = Field(ge=0, le=1)
    count: int = Field(ge=2, le=5)
    metadata: dict[str, str]


def test_mock_provider_returns_repeatable_structured_output() -> None:
    provider = MockProvider()
    request = ModelRequest(
        capability=Capability.TEXT,
        prompt="只处理合成测试数据",
        response_model=MockTextResult,
        inputs={"topic": "AI 科技"},
    )

    first = asyncio.run(provider.generate_structured(request))
    second = asyncio.run(provider.generate_structured(request))
    changed = asyncio.run(
        provider.generate_structured(
            ModelRequest(
                capability=Capability.TEXT,
                prompt="不同提示词",
                response_model=MockTextResult,
                inputs={"topic": "AI 科技"},
            )
        )
    )

    assert first == second
    assert first != changed
    assert first.content.startswith("mock-content-")
    assert first.fingerprint == second.fingerprint
    assert provider.status is AdapterStatus.VERIFIED


def test_mock_provider_supports_embedding_contract_without_network() -> None:
    provider = MockProvider()
    request = ModelRequest(
        capability=Capability.EMBEDDING,
        prompt="合成向量输入",
        response_model=MockEmbeddingResult,
    )

    output = asyncio.run(provider.generate_structured(request))

    assert len(output.vector) == 4
    assert all(-1 <= value <= 1 for value in output.vector)


def test_mock_provider_rejects_capabilities_it_does_not_declare() -> None:
    provider = MockProvider(capabilities=frozenset({Capability.TEXT}))

    with pytest.raises(IncompatibleModelError, match="image"):
        asyncio.run(
            provider.generate_structured(
                ModelRequest(
                    capability=Capability.IMAGE,
                    prompt="合成封面",
                    response_model=MockTextResult,
                )
            )
        )


@pytest.mark.parametrize("capability", list(Capability))
def test_mock_provider_implements_every_capability_contract(
    capability: Capability,
) -> None:
    provider = MockProvider()

    output = asyncio.run(
        provider.generate_structured(
            ModelRequest(
                capability=capability,
                prompt=f"synthetic-{capability.value}",
                response_model=MockCapabilityResult,
            )
        )
    )

    assert output.kind == "mock"
    assert output.label.startswith("mock-label-")


def test_mock_provider_supports_common_structured_schema_types_and_constraints() -> None:
    provider = MockProvider()

    output = asyncio.run(
        provider.generate_structured(
            ModelRequest(
                capability=Capability.VISION,
                prompt="synthetic-rich-schema",
                response_model=MockRichResult,
            )
        )
    )

    assert isinstance(output.id, UUID)
    assert output.tone in set(MockTone)
    assert 0 <= output.confidence <= 1
    assert 2 <= output.count <= 5
    assert output.metadata
