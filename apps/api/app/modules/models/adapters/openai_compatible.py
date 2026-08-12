from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx
from pydantic import SecretStr
from pydantic_core import to_jsonable_python

from app.modules.models.adapters.qianwen import (
    AttemptGovernor,
    ModelErrorCode,
    QianwenProvider,
    Sleeper,
    _SYSTEM_POLICY,
)
from app.modules.models.capabilities import AdapterStatus, Capability, ModelRequest
from app.core.logging import emit_log
from app.modules.models.openai_compatible_endpoint import (
    Resolver,
    normalize_openai_base_url,
)


_logger = logging.getLogger("operations_ai.models.openai_compatible")


class OpenAICompatibleTextProvider(QianwenProvider):
    """Strict structured-text adapter for user-provided OpenAI endpoints."""

    capabilities = frozenset({Capability.TEXT})
    status = AdapterStatus.COMMUNITY

    def __init__(
        self,
        *,
        api_key: SecretStr,
        model_id: str,
        base_url: str,
        app_env: str,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver | None = None,
        timeout_seconds: float = 30.0,
        sleeper: Sleeper = asyncio.sleep,
        usage_governor: AttemptGovernor | None = None,
    ) -> None:
        endpoint = normalize_openai_base_url(
            base_url,
            app_env=app_env,
            **({"resolver": resolver} if resolver is not None else {}),
        )
        self._api_key = api_key
        self._endpoint = endpoint.chat_completions_url
        self._model_id = model_id
        self._transport = transport
        self._timeout = httpx.Timeout(timeout_seconds)
        self._sleeper = sleeper
        self._usage_governor = usage_governor

    def _request_payload(
        self,
        request: ModelRequest[Any],
    ) -> dict[str, object]:
        user_envelope = {
            "inputs": to_jsonable_python(dict(request.inputs)),
            "output_schema": request.response_model.model_json_schema(),
            "prompt": request.prompt,
        }
        return {
            "model": self._model_id,
            "messages": [
                {"role": "system", "content": _SYSTEM_POLICY},
                {
                    "role": "user",
                    "content": json.dumps(
                        user_envelope,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "stream": False,
        }

    def _log_attempt(
        self,
        *,
        attempt: int,
        started: float,
        provider_request_id: str | None = None,
        usage: dict[str, int] | None = None,
        error_code: ModelErrorCode | None = None,
    ) -> None:
        emit_log(
            _logger,
            event="model.provider.attempt",
            message_code="MODEL_PROVIDER_ATTEMPT",
            provider="openai_compatible",
            model_id=self._model_id,
            provider_request_id=provider_request_id,
            prompt_tokens=(usage or {}).get("prompt_tokens"),
            completion_tokens=(usage or {}).get("completion_tokens"),
            total_tokens=(usage or {}).get("total_tokens"),
            latency_ms=round((time.monotonic() - started) * 1000, 3),
            attempt=attempt,
            error_code=(
                error_code.value
                if error_code is not None
                else None
            ),
        )
