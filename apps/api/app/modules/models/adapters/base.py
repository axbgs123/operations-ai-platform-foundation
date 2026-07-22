from typing import Protocol

from app.modules.models.capabilities import (
    AdapterStatus,
    Capability,
    ModelRequest,
    StructuredOutput,
)


class ModelAdapter(Protocol):
    capabilities: frozenset[Capability]
    status: AdapterStatus

    async def generate_structured(
        self,
        request: ModelRequest[StructuredOutput],
    ) -> StructuredOutput: ...
