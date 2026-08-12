from typing import Any

import httpx
from pydantic import SecretStr

from app.modules.models.adapters.qianwen import ModelErrorCode
from app.modules.models.catalog import (
    QianwenRegion,
    build_qianwen_files_endpoint,
)


def probe_qianwen_connection(
    *,
    api_key: SecretStr,
    region: QianwenRegion,
    provider_workspace_id: str | None,
    transport: httpx.BaseTransport | None = None,
    timeout_seconds: float = 10.0,
) -> str | None:
    """Validate endpoint authentication without invoking a model.

    The response body is never returned or logged. A successful probe only
    proves that the configured credential can authenticate against the
    provider API; model capability validation remains a separate controlled
    real-call acceptance step.
    """

    endpoint = build_qianwen_files_endpoint(region, provider_workspace_id)
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
            response = client.get(endpoint, headers=headers)
    except httpx.TimeoutException:
        return ModelErrorCode.TIMEOUT.value
    except httpx.RequestError:
        return ModelErrorCode.PROVIDER_UNAVAILABLE.value

    if response.status_code in {401, 403}:
        return ModelErrorCode.AUTHENTICATION_FAILED.value
    if response.status_code == 429:
        return ModelErrorCode.RATE_LIMITED.value
    if response.status_code >= 400:
        return ModelErrorCode.PROVIDER_UNAVAILABLE.value
    try:
        payload: Any = response.json()
    except ValueError:
        return ModelErrorCode.INVALID_RESPONSE.value
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return ModelErrorCode.INVALID_RESPONSE.value
    return None
