import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from app.modules.models.adapters.qianwen import ModelProviderError
from app.modules.models.catalog import (
    QIANWEN_NATIVE_SEARCH_CONTRACT_VERSION,
    QianwenRegion,
)
from app.modules.models.native_search import (
    QianwenNativeWebSearchProvider,
)


def test_qianwen_native_search_requires_tool_call_and_https_citations() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"x-request-id": "req-search-1"},
            json={
                "output": [
                    {
                        "id": "ws_1",
                        "type": "web_search_call",
                        "status": "completed",
                    },
                    {
                        "type": "message",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"summary":"官方资料摘要","key_points":["要点一"]}',
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "url": "https://help.aliyun.com/zh/model-studio/web-search/",
                                        "title": "联网搜索",
                                    }
                                ],
                            }
                        ],
                    },
                ],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 8,
                    "total_tokens": 18,
                },
            },
        )

    provider = QianwenNativeWebSearchProvider(
        api_key=SecretStr("sk-test"),
        region=QianwenRegion.CN_BEIJING,
        provider_workspace_id=None,
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(provider.search("千问联网搜索官方文档"))

    assert seen["url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1/responses"
    payload = seen["payload"]
    assert isinstance(payload, dict)
    assert payload["tools"] == [
        {"type": "web_search"},
        {"type": "web_extractor"},
    ]
    assert payload["store"] is False
    assert payload["enable_thinking"] is True
    assert "extra_body" not in payload
    assert result.contract_version == QIANWEN_NATIVE_SEARCH_CONTRACT_VERSION
    assert result.summary == "官方资料摘要"
    assert result.key_points == ("要点一",)
    assert (
        result.sources[0].url == "https://help.aliyun.com/zh/model-studio/web-search/"
    )
    assert result.sources[0].host == "help.aliyun.com"


@pytest.mark.parametrize(
    "output",
    [
        [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": '{"summary":"声称搜索过","key_points":[]}',
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://example.com/source",
                                "title": "来源",
                            }
                        ],
                    }
                ],
            }
        ],
        [
            {"type": "web_search_call", "status": "completed"},
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": '{"summary":"没有引用","key_points":[]}',
                        "annotations": [],
                    }
                ],
            },
        ],
    ],
)
def test_qianwen_native_search_rejects_unverifiable_results(
    output: list[dict[str, object]],
) -> None:
    provider = QianwenNativeWebSearchProvider(
        api_key=SecretStr("sk-test"),
        region=QianwenRegion.CN_BEIJING,
        provider_workspace_id=None,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"output": output})
        ),
    )

    with pytest.raises(ModelProviderError) as caught:
        asyncio.run(provider.search("测试"))

    assert caught.value.code.value == "MODEL_INVALID_RESPONSE"


def test_qianwen_native_search_rejects_non_https_and_duplicate_sources() -> None:
    provider = QianwenNativeWebSearchProvider(
        api_key=SecretStr("sk-test"),
        region=QianwenRegion.CN_BEIJING,
        provider_workspace_id=None,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "output": [
                        {"type": "web_search_call", "status": "completed"},
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": '{"summary":"摘要","key_points":[]}',
                                    "annotations": [
                                        {
                                            "type": "url_citation",
                                            "url": "http://example.com/insecure",
                                            "title": "不安全",
                                        },
                                        {
                                            "type": "url_citation",
                                            "url": "https://example.com/a#fragment",
                                            "title": "安全来源",
                                        },
                                        {
                                            "type": "url_citation",
                                            "url": "https://example.com/a#other",
                                            "title": "重复来源",
                                        },
                                    ],
                                }
                            ],
                        },
                    ]
                },
            )
        ),
    )

    result = asyncio.run(provider.search("测试"))

    assert len(result.sources) == 1
    assert result.sources[0].url == "https://example.com/a"
