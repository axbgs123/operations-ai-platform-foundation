from __future__ import annotations

from collections.abc import Callable, Sequence
import logging
import math
import re
import time
from typing import Any
from uuid import UUID

import httpx
from pydantic import SecretStr

from app.core.logging import emit_log
from app.modules.models.adapters.qianwen import (
    ModelErrorCode,
    ModelProviderError,
)
from app.modules.models.capabilities import AdapterStatus, Capability
from app.modules.models.catalog import (
    QIANWEN_EMBEDDING_CONTRACT_VERSION,
    QIANWEN_EMBEDDING_DIMENSION,
    QIANWEN_EMBEDDING_MODEL_ID,
    QianwenRegion,
    build_qianwen_embedding_endpoint,
    get_catalog_entry,
)


_logger = logging.getLogger("operations_ai.models.qianwen_embedding")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_EMBEDDING_BATCH_SIZE = 10
MAX_EMBEDDING_TEXT_CHARS = 8_000
MAX_EMBEDDING_BATCH_CHARS = 24_000
MAX_EMBEDDING_TEXT_UTF8_BYTES = 24_000
MAX_EMBEDDING_BATCH_UTF8_BYTES = 72_000
Sleeper = Callable[[float], None]


class QianwenRiskEmbedder:
    """Strict OpenAI-compatible adapter for the pinned internal contract.

    Character and UTF-8 byte limits are conservative application preflight
    limits. They are deliberately not described as token counts; the provider
    remains authoritative for the region-specific token limit.
    """

    capabilities = frozenset({Capability.EMBEDDING})
    status = AdapterStatus.EXPERIMENTAL
    model_id: str = QIANWEN_EMBEDDING_MODEL_ID
    dimension: int = QIANWEN_EMBEDDING_DIMENSION
    contract_version: str = QIANWEN_EMBEDDING_CONTRACT_VERSION

    def __init__(
        self,
        *,
        workspace_id: UUID,
        model_config_id: UUID,
        region: QianwenRegion,
        provider_workspace_id: str,
        api_key: SecretStr,
        model_id: str = QIANWEN_EMBEDDING_MODEL_ID,
        contract_version: str = QIANWEN_EMBEDDING_CONTRACT_VERSION,
        dimension: int = QIANWEN_EMBEDDING_DIMENSION,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 30.0,
        sleeper: Sleeper = time.sleep,
    ) -> None:
        catalog = get_catalog_entry("qianwen", model_id)
        if catalog.capabilities != frozenset({Capability.EMBEDDING}):
            raise ValueError("configured model is not the embedding model")
        if contract_version != catalog.contract_version:
            raise ValueError("unsupported embedding contract version")
        if dimension != catalog.embedding_dimension:
            raise ValueError("unsupported embedding dimension")
        if region not in catalog.available_regions:
            raise ValueError("unsupported Qianwen region")
        self.workspace_id = workspace_id
        self.model_config_id = model_config_id
        self.region = region
        self.model_id = model_id
        self.contract_version = contract_version
        self.dimension = dimension
        self._api_key = api_key
        self._endpoint = build_qianwen_embedding_endpoint(
            region, provider_workspace_id
        )
        self._transport = transport
        self._timeout = httpx.Timeout(timeout_seconds)
        self._sleeper = sleeper

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        safe_texts = self._validate_input(texts)
        payload = {
            "model": self.model_id,
            "input": safe_texts,
            "dimensions": self.dimension,
            "encoding_format": "float",
        }
        headers = {
            "Authorization": f"Bearer {self._api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        with httpx.Client(
            transport=self._transport,
            timeout=self._timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            for attempt in (1, 2):
                started = time.monotonic()
                try:
                    response = client.post(
                        self._endpoint, headers=headers, json=payload
                    )
                except httpx.TimeoutException:
                    self._log(attempt, started, ModelErrorCode.TIMEOUT, len(safe_texts))
                    if attempt == 1:
                        self._sleeper(0.25)
                        continue
                    raise ModelProviderError(ModelErrorCode.TIMEOUT) from None
                except httpx.RequestError:
                    self._log(
                        attempt,
                        started,
                        ModelErrorCode.PROVIDER_UNAVAILABLE,
                        len(safe_texts),
                    )
                    raise ModelProviderError(
                        ModelErrorCode.PROVIDER_UNAVAILABLE
                    ) from None

                error = self._http_error(response.status_code)
                request_id = self._request_id(response)
                if error is not None:
                    self._log(
                        attempt,
                        started,
                        error,
                        len(safe_texts),
                        request_id=request_id,
                    )
                    if attempt == 1 and (
                        response.status_code == 429
                        or response.status_code >= 500
                    ):
                        self._sleeper(0.25)
                        continue
                    raise ModelProviderError(
                        error, provider_request_id=request_id
                    )
                try:
                    vectors = self._parse(response, len(safe_texts))
                except (KeyError, TypeError, ValueError, IndexError):
                    self._log(
                        attempt,
                        started,
                        ModelErrorCode.EMBEDDING_INVALID_RESPONSE,
                        len(safe_texts),
                        request_id=request_id,
                    )
                    raise ModelProviderError(
                        ModelErrorCode.EMBEDDING_INVALID_RESPONSE,
                        provider_request_id=request_id,
                    ) from None
                usage = self._usage(response)
                self._log(
                    attempt,
                    started,
                    None,
                    len(safe_texts),
                    request_id=request_id,
                    prompt_tokens=usage.get("prompt_tokens"),
                    total_tokens=usage.get("total_tokens"),
                )
                return vectors
        raise AssertionError("embedding retry loop must return or raise")

    @staticmethod
    def _validate_input(texts: Sequence[str]) -> list[str]:
        if isinstance(texts, (str, bytes)):
            raise ValueError("embedding input must be a sequence of texts")
        values = list(texts)
        if not values or len(values) > MAX_EMBEDDING_BATCH_SIZE:
            raise ValueError("embedding batch must contain between 1 and 10 texts")
        total_chars = 0
        total_bytes = 0
        for text in values:
            if not isinstance(text, str) or not text.strip():
                raise ValueError("embedding text must be non-empty")
            chars = len(text)
            utf8_bytes = len(text.encode("utf-8"))
            if chars > MAX_EMBEDDING_TEXT_CHARS:
                raise ValueError("embedding text exceeds character limit")
            if utf8_bytes > MAX_EMBEDDING_TEXT_UTF8_BYTES:
                raise ValueError("embedding text exceeds UTF-8 byte limit")
            total_chars += chars
            total_bytes += utf8_bytes
        if total_chars > MAX_EMBEDDING_BATCH_CHARS:
            raise ValueError("embedding batch exceeds character limit")
        if total_bytes > MAX_EMBEDDING_BATCH_UTF8_BYTES:
            raise ValueError("embedding batch exceeds UTF-8 byte limit")
        return values

    def _parse(
        self, response: httpx.Response, input_count: int
    ) -> list[list[float]]:
        envelope: Any = response.json()
        if not isinstance(envelope, dict):
            raise TypeError
        if envelope.get("model") != self.model_id:
            raise ValueError
        data = envelope["data"]
        if not isinstance(data, list) or len(data) != input_count:
            raise ValueError
        by_index: dict[int, list[float]] = {}
        for item in data:
            if not isinstance(item, dict):
                raise TypeError
            index = item["index"]
            vector = item["embedding"]
            if (
                item.get("object") != "embedding"
                or
                not isinstance(index, int)
                or isinstance(index, bool)
                or index < 0
                or index >= input_count
                or index in by_index
            ):
                raise ValueError
            if not isinstance(vector, list) or len(vector) != self.dimension:
                raise ValueError
            parsed: list[float] = []
            for value in vector:
                if (
                    not isinstance(value, float)
                    or not math.isfinite(value)
                ):
                    raise TypeError
                parsed.append(value)
            if math.isclose(sum(value * value for value in parsed), 0.0):
                raise ValueError
            by_index[index] = parsed
        if set(by_index) != set(range(input_count)):
            raise ValueError
        return [by_index[index] for index in range(input_count)]

    @staticmethod
    def _http_error(status_code: int) -> ModelErrorCode | None:
        if status_code in {401, 403}:
            return ModelErrorCode.AUTHENTICATION_FAILED
        if status_code == 429:
            return ModelErrorCode.RATE_LIMITED
        if status_code >= 400:
            return ModelErrorCode.PROVIDER_UNAVAILABLE
        return None

    @staticmethod
    def _request_id(response: httpx.Response) -> str | None:
        candidate = response.headers.get("x-request-id")
        if candidate is not None and _REQUEST_ID.fullmatch(candidate):
            return candidate
        return None

    @staticmethod
    def _usage(response: httpx.Response) -> dict[str, int]:
        try:
            usage = response.json().get("usage", {})
        except (TypeError, ValueError):
            return {}
        if not isinstance(usage, dict):
            return {}
        return {
            name: value
            for name in ("prompt_tokens", "total_tokens")
            if isinstance((value := usage.get(name)), int)
            and not isinstance(value, bool)
            and value >= 0
        }

    def _log(
        self,
        attempt: int,
        started: float,
        error: ModelErrorCode | None,
        input_count: int,
        *,
        request_id: str | None = None,
        prompt_tokens: int | None = None,
        total_tokens: int | None = None,
    ) -> None:
        emit_log(
            _logger,
            event="model.provider.embedding_attempt",
            message_code="MODEL_PROVIDER_EMBEDDING_ATTEMPT",
            provider="qianwen",
            model_id=self.model_id,
            model_contract_version=self.contract_version,
            embedding_dimension=self.dimension,
            input_count=input_count,
            provider_request_id=request_id,
            prompt_tokens=prompt_tokens,
            total_tokens=total_tokens,
            latency_ms=round((time.monotonic() - started) * 1000, 3),
            attempt=attempt,
            error_code=error.value if error is not None else None,
        )
