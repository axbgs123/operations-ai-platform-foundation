from typing import Any

import httpx
from pydantic import SecretStr

from app.modules.models.adapters.qianwen import ModelErrorCode
from app.modules.models.openai_compatible_endpoint import (
    NormalizedProviderEndpoint,
    Resolver,
    UnsafeProviderEndpoint,
    normalize_openai_base_url,
)


def _validate_peer(
    response: httpx.Response,
    *,
    endpoint: NormalizedProviderEndpoint,
) -> None:
    stream = response.extensions.get("network_stream")
    if stream is None:
        return
    peer = stream.get_extra_info("server_addr")
    if peer is None:
        peer = stream.get_extra_info("peername")
    if peer is None:
        raise UnsafeProviderEndpoint("provider peer address is unavailable")
    endpoint.require_peer(str(peer[0]))


def probe_openai_compatible_connection(
    *,
    api_key: SecretStr,
    base_url: str,
    model_id: str,
    app_env: str,
    transport: httpx.BaseTransport | None = None,
    resolver: Resolver | None = None,
    timeout_seconds: float = 10.0,
) -> str | None:
    try:
        endpoint = normalize_openai_base_url(
            base_url,
            app_env=app_env,
            **({"resolver": resolver} if resolver is not None else {}),
        )
    except UnsafeProviderEndpoint:
        return "MODEL_ENDPOINT_UNSAFE"
    headers = {
        "Authorization": f"Bearer {api_key.get_secret_value()}",
        "Accept": "application/json",
    }
    try:
        with httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = client.get(endpoint.models_url, headers=headers)
        _validate_peer(response, endpoint=endpoint)
    except UnsafeProviderEndpoint:
        return "MODEL_ENDPOINT_UNSAFE"
    except httpx.TimeoutException:
        return ModelErrorCode.TIMEOUT.value
    except httpx.RequestError:
        return ModelErrorCode.PROVIDER_UNAVAILABLE.value

    if response.status_code in {401, 403}:
        return ModelErrorCode.AUTHENTICATION_FAILED.value
    if response.status_code == 429:
        return ModelErrorCode.RATE_LIMITED.value
    if response.is_redirect or response.status_code >= 400:
        return ModelErrorCode.PROVIDER_UNAVAILABLE.value
    try:
        payload: Any = response.json()
    except ValueError:
        return ModelErrorCode.INVALID_RESPONSE.value
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return ModelErrorCode.INVALID_RESPONSE.value
    models = payload["data"]
    for item in models:
        if isinstance(item, dict) and item.get("id") == model_id:
            return None
    return "MODEL_NOT_FOUND"
