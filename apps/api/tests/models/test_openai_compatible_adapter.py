import asyncio
import json
from collections.abc import Callable

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr
import pytest

from app.modules.models.adapters.openai_compatible import (
    OpenAICompatibleTextProvider,
)
from app.modules.models.adapters.qianwen import ModelErrorCode, ModelProviderError
from app.modules.models.capabilities import Capability, ModelRequest


class StrictReply(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    reply: str


def _request() -> ModelRequest[StrictReply]:
    return ModelRequest(
        capability=Capability.TEXT,
        prompt="reply using the schema",
        response_model=StrictReply,
        inputs={"message": "你好"},
    )


def _response(content: str = '{"reply":"你好"}', status: int = 200) -> httpx.Response:
    if status != 200:
        return httpx.Response(status, json={"error": "unsafe-body"})
    return httpx.Response(
        200,
        json={
            "choices": [{"finish_reason": "stop", "message": {"content": content}}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 3},
        },
    )


def _provider(
    handler: Callable[[httpx.Request], httpx.Response],
) -> OpenAICompatibleTextProvider:
    async def no_sleep(delay: float) -> None:
        return None

    return OpenAICompatibleTextProvider(
        api_key=SecretStr("synthetic-key-never-real"),
        model_id="example-chat",
        base_url="https://api.example.com/v1",
        app_env="production",
        transport=httpx.MockTransport(handler),
        resolver=lambda host, port, type: [
            (2, 1, 6, "", ("93.184.216.34", port))
        ],
        sleeper=no_sleep,
    )


def test_strict_structured_request_uses_standard_openai_fields_only() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _response()

    result = asyncio.run(_provider(handler).generate_structured(_request()))

    assert result.reply == "你好"
    payload = json.loads(captured[0].content)
    assert captured[0].url == "https://api.example.com/v1/chat/completions"
    assert payload["model"] == "example-chat"
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["stream"] is False
    assert "enable_thinking" not in payload
    assert "inputs" in json.loads(payload["messages"][1]["content"])


@pytest.mark.parametrize(
    "content",
    [
        "```json\n{\"reply\":\"你好\"}\n```",
        '{"reply":"你好","extra":true}',
        '{"reply":7}',
        '{"reply":',
    ],
)
def test_non_strict_content_is_rejected(content: str) -> None:
    with pytest.raises(ModelProviderError) as caught:
        asyncio.run(
            _provider(lambda request: _response(content)).generate_structured(
                _request()
            )
        )

    assert caught.value.code is ModelErrorCode.INVALID_RESPONSE


@pytest.mark.parametrize(("status", "attempts"), [(401, 1), (429, 2), (503, 2)])
def test_retry_contract_is_bounded(status: int, attempts: int) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response(status=status)

    with pytest.raises(ModelProviderError):
        asyncio.run(_provider(handler).generate_structured(_request()))

    assert calls == attempts
