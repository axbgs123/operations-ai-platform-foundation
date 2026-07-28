import asyncio
from typing import cast

from app.modules.generation.text_service import (
    GeneratedTextDraft,
    TextGenerationRequest,
)
from app.modules.models.capabilities import ModelRequest


class RecordingProvider:
    def __init__(self, result: GeneratedTextDraft) -> None:
        self.result = result
        self.requests: list[ModelRequest[GeneratedTextDraft]] = []

    async def generate_structured(
        self,
        request: ModelRequest[GeneratedTextDraft],
    ) -> GeneratedTextDraft:
        self.requests.append(request)
        return self.result


def _request() -> TextGenerationRequest:
    return TextGenerationRequest(
        policy=(
            "所有事实性表达必须来自 confirmed_facts，"
            "并在 claims 中逐条声明。"
        ),
        inputs={
            "platform": "douyin",
            "target": "提升互动",
            "confirmed_facts": [
                {
                    "item_id": "11111111-1111-1111-1111-111111111111",
                    "field_code": "price",
                    "value": "199 元",
                    "source_id": "22222222-2222-2222-2222-222222222222",
                    "source_level": "L1",
                }
            ],
            "style": {
                "profile_id": "33333333-3333-3333-3333-333333333333",
                "version": 3,
                "style_json": '{"copy":{"tones":["克制"]}}',
            },
            "viral_references": [
                {
                    "library_item_id": "44444444-4444-4444-4444-444444444444",
                    "content_id": "55555555-5555-5555-5555-555555555555",
                    "category": "engagement",
                    "strategy_tags": ["结论前置"],
                    "applicable_scenarios": ["新品"],
                    "structure_summary": "问题—证据—行动",
                }
            ],
            "user_prompt": "保持克制",
            "source_assets": [
                {
                    "source_id": "66666666-6666-6666-6666-666666666666",
                    "kind": "url",
                    "content_sha256": "a" * 64,
                    "file_name": "../../private.txt",
                    "source_url": "https://objects.example.test/private?token=secret",
                }
            ],
            "risk_rule_version": "douyin-risk-v1",
        },
    )


def test_text_adapter_uses_strict_draft_schema_and_only_safe_text_inputs() -> None:
    from app.modules.models.adapters.qianwen_text_generation import (
        QianwenTextGenerationAdapter,
    )

    provider = RecordingProvider(
        GeneratedTextDraft(
            titles=("标题一", "标题二", "标题三"),
            copy="售价为 199 元。",
            claims=({"field_name": "price", "value": "199 元"},),
        )
    )

    result = asyncio.run(
        QianwenTextGenerationAdapter(
            cast("object", provider),
        ).generate(_request())
    )

    assert result.claims[0].value == "199 元"
    sent = provider.requests[0]
    assert sent.response_model is GeneratedTextDraft
    assert sent.prompt == _request().policy
    assert sent.inputs == {
        "platform": "douyin",
        "target": "提升互动",
        "confirmed_facts": [
            {
                "field_name": "price",
                "value": "199 元",
                "source_level": "L1",
            }
        ],
        "style": {"copy": {"tones": ["克制"]}},
        "viral_references": [
            {
                "category": "engagement",
                "strategy_tags": ["结论前置"],
                "applicable_scenarios": ["新品"],
                "structure_summary": "问题—证据—行动",
            }
        ],
        "user_prompt": "保持克制",
        "source_materials": {"confirmed": True, "count": 1},
        "risk_rule_version": "douyin-risk-v1",
    }
    serialized = str(sent.inputs)
    for forbidden in (
        "https://",
        "token=secret",
        "../../private.txt",
        "content_sha256",
        "source_id",
        "library_item_id",
        "provider_workspace_id",
    ):
        assert forbidden not in serialized


def test_text_adapter_does_not_repair_or_synthesize_provider_claims() -> None:
    from app.modules.models.adapters.qianwen_text_generation import (
        QianwenTextGenerationAdapter,
    )

    provider = RecordingProvider(
        GeneratedTextDraft(
            titles=("标题一", "标题二", "标题三"),
            copy="模型自行添加蓝色事实。",
            claims=({"field_name": "color", "value": "蓝色"},),
        )
    )

    result = asyncio.run(
        QianwenTextGenerationAdapter(
            cast("object", provider),
        ).generate(_request())
    )

    assert result.claims == (
        result.claims[0].model_copy(),
    )
    assert result.claims[0].field_name == "color"
