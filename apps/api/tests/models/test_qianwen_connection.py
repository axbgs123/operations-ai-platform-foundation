import httpx
from pydantic import SecretStr

from app.modules.models.connection_test import probe_qianwen_connection
from app.modules.models.catalog import QianwenRegion


def test_connection_probe_uses_official_global_endpoint_without_model_call() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"data": [], "has_more": False})

    result = probe_qianwen_connection(
        api_key=SecretStr("sk-ws-synthetic-never-real"),
        region=QianwenRegion.CN_BEIJING,
        provider_workspace_id=None,
        transport=httpx.MockTransport(handler),
    )

    assert result is None
    assert len(captured) == 1
    assert str(captured[0].url) == (
        "https://dashscope.aliyuncs.com/compatible-mode/v1/files?limit=1"
    )
    assert captured[0].headers["authorization"] == (
        "Bearer sk-ws-synthetic-never-real"
    )
    assert captured[0].method == "GET"
    assert captured[0].content == b""


def test_connection_probe_returns_safe_authentication_error() -> None:
    result = probe_qianwen_connection(
        api_key=SecretStr("sk-ws-synthetic-never-real"),
        region=QianwenRegion.CN_BEIJING,
        provider_workspace_id=None,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                401,
                json={"message": "provider-secret-body-never-expose"},
            )
        ),
    )

    assert result == "MODEL_AUTHENTICATION_FAILED"
    assert "provider-secret-body-never-expose" not in result
