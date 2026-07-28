from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from io import BytesIO
import logging
import math
import re
import time
from typing import Any
from uuid import UUID

import httpx
from PIL import Image, UnidentifiedImageError
from pydantic import SecretStr

from app.core.logging import emit_log
from app.modules.content.account_models import Platform
from app.modules.imports.ocr_adapters import (
    RecognitionRegion,
    RecognizedMetricCandidate,
    RecognizedTextRegion,
    VisionRecognition,
)
from app.modules.models.adapters.qianwen import (
    ModelErrorCode,
    ModelProviderError,
)
from app.modules.models.capabilities import AdapterStatus, Capability
from app.modules.models.catalog import (
    QIANWEN_OCR_MODEL_ID,
    QianwenRegion,
    build_qianwen_ocr_endpoint,
    get_catalog_entry,
)


_logger = logging.getLogger("operations_ai.models.qianwen_vision")
_FORMAT_MIME = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
}
_VALUE = re.compile(r"^[0-9][0-9,]*(?:\.[0-9]+)?$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
Sleeper = Callable[[float], None]


class QianwenVisionAdapter:
    capabilities = frozenset({Capability.VISION})
    status = AdapterStatus.EXPERIMENTAL

    def __init__(
        self,
        *,
        workspace_id: UUID,
        model_config_id: UUID,
        expected_platform: Platform,
        region: QianwenRegion,
        provider_workspace_id: str,
        api_key: SecretStr,
        model_id: str = QIANWEN_OCR_MODEL_ID,
        contract_version: str = "qwen-ocr-advanced-v1",
        allowed_metric_labels: Mapping[str, str],
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 30.0,
        sleeper: Sleeper = time.sleep,
    ) -> None:
        catalog = get_catalog_entry("qianwen", model_id)
        if catalog.capabilities != frozenset({Capability.VISION}):
            raise ValueError("configured model is not the OCR vision model")
        if contract_version != catalog.contract_version:
            raise ValueError("unsupported OCR contract version")
        if region not in catalog.available_regions:
            raise ValueError("unsupported Qianwen region")
        self.workspace_id = workspace_id
        self.model_config_id = model_config_id
        self.expected_platform = expected_platform
        self._api_key = api_key
        self._model_id = model_id
        self._contract_version = contract_version
        self._catalog = catalog
        self._endpoint = build_qianwen_ocr_endpoint(
            region, provider_workspace_id
        )
        self._labels = dict(allowed_metric_labels)
        self._transport = transport
        self._timeout = httpx.Timeout(timeout_seconds)
        self._sleeper = sleeper

    def recognize(self, image: bytes, mime_type: str) -> VisionRecognition:
        sanitized, safe_mime, width, height = self._sanitize_image(
            image, mime_type
        )
        payload = self._payload(sanitized, safe_mime)
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
                    self._log(attempt, started, ModelErrorCode.TIMEOUT)
                    if attempt == 1:
                        self._sleeper(0.25)
                        continue
                    raise ModelProviderError(ModelErrorCode.TIMEOUT) from None
                except httpx.RequestError:
                    self._log(
                        attempt,
                        started,
                        ModelErrorCode.PROVIDER_UNAVAILABLE,
                    )
                    raise ModelProviderError(
                        ModelErrorCode.PROVIDER_UNAVAILABLE
                    ) from None
                error = self._http_error(response.status_code)
                if error is not None:
                    self._log(attempt, started, error)
                    if attempt == 1 and (
                        response.status_code == 429
                        or response.status_code >= 500
                    ):
                        self._sleeper(0.25)
                        continue
                    raise ModelProviderError(error)
                result = self._parse(response, width=width, height=height)
                self._log(
                    attempt,
                    started,
                    None,
                    request_id=result.provider_request_id,
                    image_tokens=result.image_tokens,
                )
                return result
        raise AssertionError("OCR retry loop must return or raise")

    def _sanitize_image(
        self, image: bytes, declared_mime: str
    ) -> tuple[bytes, str, int, int]:
        if (
            declared_mime not in self._catalog.supported_mime_types
            or not image
        ):
            raise ModelProviderError(ModelErrorCode.IMAGE_INVALID)
        assert self._catalog.max_image_bytes is not None
        if len(image) > self._catalog.max_image_bytes:
            raise ModelProviderError(ModelErrorCode.IMAGE_TOO_LARGE)
        try:
            with Image.open(BytesIO(image)) as decoded:
                decoded.verify()
            with Image.open(BytesIO(image)) as decoded:
                image_format = decoded.format
                actual_mime = _FORMAT_MIME.get(str(image_format))
                if actual_mime != declared_mime or getattr(
                    decoded, "is_animated", False
                ):
                    raise ModelProviderError(ModelErrorCode.IMAGE_INVALID)
                width, height = decoded.size
                if width <= 10 or height <= 10:
                    raise ModelProviderError(ModelErrorCode.IMAGE_INVALID)
                assert self._catalog.max_pixels is not None
                if width * height > self._catalog.max_pixels:
                    raise ModelProviderError(ModelErrorCode.IMAGE_TOO_LARGE)
                clean = decoded.convert("RGB")
                output = BytesIO()
                if actual_mime == "image/png":
                    clean.save(output, "PNG", optimize=True)
                elif actual_mime == "image/jpeg":
                    clean.save(output, "JPEG", quality=92, optimize=True)
                else:
                    clean.save(output, "WEBP", quality=92, method=4)
                return output.getvalue(), actual_mime, width, height
        except ModelProviderError:
            raise
        except (Image.DecompressionBombError, OSError, UnidentifiedImageError):
            raise ModelProviderError(ModelErrorCode.IMAGE_INVALID) from None

    def _payload(self, image: bytes, mime_type: str) -> dict[str, object]:
        encoded = base64.b64encode(image).decode("ascii")
        return {
            "model": self._model_id,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "image": f"data:{mime_type};base64,{encoded}",
                                "min_pixels": self._catalog.min_pixels,
                                "max_pixels": self._catalog.max_pixels,
                                "enable_rotate": True,
                            }
                        ],
                    }
                ]
            },
            "parameters": {
                "ocr_options": {"task": "advanced_recognition"},
                "max_tokens": self._catalog.max_output_tokens,
            },
        }

    def _parse(
        self, response: httpx.Response, *, width: int, height: int
    ) -> VisionRecognition:
        try:
            envelope: Any = response.json()
            request_id = envelope["request_id"]
            content = envelope["output"]["choices"][0]["message"]["content"]
            if not isinstance(content, list):
                raise TypeError
            ocr_result = content[0]["ocr_result"]
            words = ocr_result["words_info"]
            if not isinstance(words, list):
                raise TypeError
            safe_request_id = (
                request_id
                if isinstance(request_id, str)
                and _REQUEST_ID.fullmatch(request_id)
                else None
            )
            usage = envelope.get("usage", {})
            image_tokens = (
                usage.get("image_tokens") if isinstance(usage, dict) else None
            )
            if not isinstance(image_tokens, int) or isinstance(
                image_tokens, bool
            ) or image_tokens < 0:
                image_tokens = None
            text_regions: list[RecognizedTextRegion] = []
            metrics: list[RecognizedMetricCandidate] = []
            unmapped: list[str] = []
            for word in words:
                if not isinstance(word, dict):
                    raise TypeError
                text = word["text"]
                location = word["location"]
                rotate_rect = word.get("rotate_rect")
                if not isinstance(text, str) or not text.strip():
                    raise TypeError
                region = self._region(location, width=width, height=height)
                rotation = self._rotation(rotate_rect)
                clean_text = text.strip()
                text_regions.append(
                    RecognizedTextRegion(
                        text=clean_text,
                        region=region,
                        rotate_rect=rotation,
                    )
                )
                mapped = self._metric(clean_text, region)
                if mapped is None:
                    unmapped.append(clean_text)
                else:
                    metrics.append(mapped)
            return VisionRecognition(
                platform=self.expected_platform.value,
                platform_confidence=0,
                metric_candidates=metrics,
                text_regions=tuple(text_regions),
                unmapped_text=tuple(unmapped),
                confidence_source="unavailable",
                requires_human_review=True,
                model_id=self._model_id,
                contract_version=self._contract_version,
                provider_request_id=safe_request_id,
                image_tokens=image_tokens,
            )
        except ModelProviderError:
            raise
        except (KeyError, IndexError, TypeError, ValueError):
            raise ModelProviderError(
                ModelErrorCode.OCR_INVALID_RESPONSE
            ) from None

    @staticmethod
    def _region(
        location: object, *, width: int, height: int
    ) -> RecognitionRegion:
        if (
            not isinstance(location, list)
            or len(location) != 8
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in location
            )
        ):
            raise ModelProviderError(ModelErrorCode.OCR_INVALID_RESPONSE)
        xs = [float(location[index]) for index in (0, 2, 4, 6)]
        ys = [float(location[index]) for index in (1, 3, 5, 7)]
        if min(xs) < 0 or max(xs) > width or min(ys) < 0 or max(ys) > height:
            raise ModelProviderError(ModelErrorCode.OCR_INVALID_RESPONSE)
        left, right = min(xs), max(xs)
        top, bottom = min(ys), max(ys)
        if left >= right or top >= bottom:
            raise ModelProviderError(ModelErrorCode.OCR_INVALID_RESPONSE)
        return RecognitionRegion(
            x=left / width,
            y=top / height,
            width=(right - left) / width,
            height=(bottom - top) / height,
        )

    @staticmethod
    def _rotation(value: object) -> tuple[float, float, float, float, float] | None:
        if value is None:
            return None
        if (
            not isinstance(value, list)
            or len(value) != 5
            or any(
                isinstance(item, bool)
                or not isinstance(item, (int, float))
                or not math.isfinite(item)
                for item in value
            )
        ):
            raise ModelProviderError(ModelErrorCode.OCR_INVALID_RESPONSE)
        result = tuple(float(item) for item in value)
        if result[2] <= 0 or result[3] <= 0 or not -90 <= result[4] <= 90:
            raise ModelProviderError(ModelErrorCode.OCR_INVALID_RESPONSE)
        return result  # type: ignore[return-value]

    def _metric(
        self, text: str, region: RecognitionRegion
    ) -> RecognizedMetricCandidate | None:
        for label, key in self._labels.items():
            if not text.startswith(label):
                continue
            remainder = text[len(label) :].strip().lstrip(":：").strip()
            if not _VALUE.fullmatch(remainder):
                return None
            return RecognizedMetricCandidate(
                key=key,
                value=remainder.replace(",", ""),
                confidence=0,
                region=region,
            )
        return None

    @staticmethod
    def _http_error(status_code: int) -> ModelErrorCode | None:
        if status_code in {401, 403}:
            return ModelErrorCode.AUTHENTICATION_FAILED
        if status_code == 429:
            return ModelErrorCode.RATE_LIMITED
        if status_code >= 400:
            return ModelErrorCode.PROVIDER_UNAVAILABLE
        return None

    def _log(
        self,
        attempt: int,
        started: float,
        error: ModelErrorCode | None,
        *,
        request_id: str | None = None,
        image_tokens: int | None = None,
    ) -> None:
        emit_log(
            _logger,
            event="model.provider.ocr_attempt",
            message_code="MODEL_PROVIDER_OCR_ATTEMPT",
            provider="qianwen",
            model_id=self._model_id,
            provider_request_id=request_id,
            image_tokens=image_tokens,
            latency_ms=round((time.monotonic() - started) * 1000, 3),
            attempt=attempt,
            error_code=error.value if error is not None else None,
        )
