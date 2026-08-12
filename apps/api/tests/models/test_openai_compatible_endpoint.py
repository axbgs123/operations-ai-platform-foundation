import socket

import pytest

from app.modules.models.openai_compatible_endpoint import (
    UnsafeProviderEndpoint,
    normalize_openai_base_url,
)


def _public_resolver(
    host: str,
    port: int,
    *,
    type: int,
) -> list[tuple[object, ...]]:
    assert host == "api.example.com"
    assert port == 443
    assert type == socket.SOCK_STREAM
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def test_normalizes_public_https_provider_base_url() -> None:
    endpoint = normalize_openai_base_url(
        "https://API.Example.com/v1/",
        app_env="production",
        resolver=_public_resolver,
    )

    assert endpoint.base_url == "https://api.example.com/v1"
    assert endpoint.models_url == "https://api.example.com/v1/models"
    assert endpoint.chat_completions_url == (
        "https://api.example.com/v1/chat/completions"
    )
    endpoint.require_peer("93.184.216.34")


@pytest.mark.parametrize(
    "value",
    [
        "http://api.example.com/v1",
        "ftp://api.example.com/v1",
        "https://user:pass@api.example.com/v1",
        "https://api.example.com/v1?target=private",
        "https://api.example.com/v1#fragment",
        "https://api.example.com\\v1",
        "https://127.0.0.1/v1",
        "https://169.254.169.254/latest/meta-data",
    ],
)
def test_rejects_unsafe_provider_base_urls(value: str) -> None:
    with pytest.raises(UnsafeProviderEndpoint):
        normalize_openai_base_url(
            value,
            app_env="production",
            resolver=_public_resolver,
        )


def test_development_allows_explicit_loopback_http_only() -> None:
    endpoint = normalize_openai_base_url(
        "http://127.0.0.1:8080/v1",
        app_env="development",
    )

    assert endpoint.base_url == "http://127.0.0.1:8080/v1"
    endpoint.require_peer("127.0.0.1")


def test_rejects_dns_rebinding_peer() -> None:
    endpoint = normalize_openai_base_url(
        "https://api.example.com/v1",
        app_env="production",
        resolver=_public_resolver,
    )

    with pytest.raises(UnsafeProviderEndpoint, match="DNS rebind"):
        endpoint.require_peer("8.8.8.8")
