import json
from typing import Protocol

from app.modules.generation.text_service import (
    GeneratedTextDraft,
    TextGenerationRequest,
)
from app.modules.models.capabilities import Capability, ModelRequest


class StructuredTextProvider(Protocol):
    async def generate_structured(
        self,
        request: ModelRequest[GeneratedTextDraft],
    ) -> GeneratedTextDraft: ...


class QianwenTextGenerationAdapter:
    def __init__(self, provider: StructuredTextProvider) -> None:
        self._provider = provider

    async def generate(
        self,
        request: TextGenerationRequest,
    ) -> GeneratedTextDraft:
        return await self._provider.generate_structured(
            ModelRequest(
                capability=Capability.TEXT,
                prompt=request.policy,
                response_model=GeneratedTextDraft,
                inputs=_safe_generation_inputs(request.inputs),
            )
        )


def _safe_generation_inputs(
    inputs: dict[str, object],
) -> dict[str, object]:
    raw_facts = inputs.get("confirmed_facts", [])
    facts = [
        {
            "field_name": item.get("field_code"),
            "value": item.get("value"),
            "source_level": item.get("source_level"),
        }
        for item in raw_facts
        if isinstance(item, dict)
    ] if isinstance(raw_facts, (list, tuple)) else []
    style_payload: object = None
    style = inputs.get("style")
    if isinstance(style, dict):
        raw_style = style.get("style_json")
        if isinstance(raw_style, str):
            style_payload = json.loads(raw_style)
    raw_references = inputs.get("viral_references", [])
    references = [
        {
            "category": item.get("category"),
            "strategy_tags": item.get("strategy_tags"),
            "applicable_scenarios": item.get("applicable_scenarios"),
            "structure_summary": item.get("structure_summary"),
        }
        for item in raw_references
        if isinstance(item, dict)
    ] if isinstance(raw_references, (list, tuple)) else []
    source_assets = inputs.get("source_assets", [])
    source_count = len(source_assets) if isinstance(source_assets, list) else 0
    return {
        "platform": inputs.get("platform"),
        "target": inputs.get("target"),
        "confirmed_facts": facts,
        "style": style_payload,
        "viral_references": references,
        "user_prompt": inputs.get("user_prompt"),
        "source_materials": {
            "confirmed": source_count > 0,
            "count": source_count,
        },
        "risk_rule_version": inputs.get("risk_rule_version"),
    }
