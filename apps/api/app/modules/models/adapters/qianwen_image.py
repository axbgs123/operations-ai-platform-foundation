from __future__ import annotations

import base64
import hashlib
from io import BytesIO
import ipaddress
import json
import logging
import re
import socket
import time
from collections.abc import Callable, Iterable
from urllib.parse import urljoin, urlsplit
from uuid import UUID

import httpx
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, SecretStr

from app.core.logging import emit_log
from app.modules.generation.cover_models import ReferencePurpose
from app.modules.generation.cover_service import ImageModelRequest
from app.modules.models.adapters.qianwen import (
    ModelErrorCode,
    ModelProviderError,
)
from app.modules.models.capabilities import AdapterStatus, Capability
from app.modules.models.catalog import (
    QIANWEN_IMAGE_CONTRACT_VERSION,
    QIANWEN_IMAGE_MODEL_ID,
    QianwenRegion,
    build_qianwen_image_endpoint,
    get_catalog_entry,
)


QIANWEN_COVER_CONTRACT_VERSION = QIANWEN_IMAGE_CONTRACT_VERSION
MAX_REFERENCE_BYTES = 10 * 1024 * 1024
MAX_REFERENCE_EDGE = 3072
MAX_REFERENCE_PIXELS = 3072 * 3072
MAX_OUTPUT_BYTES = 25 * 1024 * 1024
MAX_REDIRECTS = 3
_SAFE_IMAGE_MIMES = frozenset({"image/png", "image/jpeg", "image/webp"})
_FORMAT_TO_MIME = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
}
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_logger = logging.getLogger("operations_ai.models.qianwen_image")


class SanitizedImage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: bytes
    mime_type: str
    width: int
    height: int
    sha256: str


class QianwenPreparedImage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_id: UUID
    asset_version: int
    purpose: ReferencePurpose
    content: bytes
    mime_type: str
    width: int
    height: int
    sha256: str

    @classmethod
    def from_untrusted_bytes(
        cls,
        *,
        asset_id: UUID,
        asset_version: int,
        purpose: ReferencePurpose,
        declared_mime_type: str,
        content: bytes,
    ) -> QianwenPreparedImage:
        cleaned = sanitize_reference_image(
            content,
            declared_mime_type=declared_mime_type,
        )
        return cls(
            asset_id=asset_id,
            asset_version=asset_version,
            purpose=purpose,
            content=cleaned.content,
            mime_type=cleaned.mime_type,
            width=cleaned.width,
            height=cleaned.height,
            sha256=cleaned.sha256,
        )

    def data_url(self) -> str:
        encoded = base64.b64encode(self.content).decode("ascii")
        return f"data:{self.mime_type};base64,{encoded}"


class ImageGenerationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_request_id: str | None
    seed: int | None
    width: int
    height: int
    input_image_count: int


def _decode_image(
    content: bytes,
    *,
    max_bytes: int,
    max_pixels: int,
    max_edge: int | None,
    error_code: ModelErrorCode,
) -> tuple[Image.Image, str]:
    if not content or len(content) > max_bytes:
        raise ModelProviderError(error_code)
    try:
        source = Image.open(BytesIO(content))
        source_format = source.format
        if (
            source_format not in _FORMAT_TO_MIME
            or getattr(source, "is_animated", False)
            or getattr(source, "n_frames", 1) != 1
        ):
            raise ValueError
        width, height = source.size
        if (
            width <= 0
            or height <= 0
            or width * height > max_pixels
            or (max_edge is not None and max(width, height) > max_edge)
        ):
            raise ValueError
        source.load()
        return source.convert("RGB"), _FORMAT_TO_MIME[source_format]
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ):
        raise ModelProviderError(error_code) from None


def _encode_png(image: Image.Image) -> bytes:
    output = BytesIO()
    image.convert("RGB").save(
        output,
        format="PNG",
        optimize=False,
        compress_level=9,
    )
    return output.getvalue()


def sanitize_reference_image(
    content: bytes,
    *,
    declared_mime_type: str,
) -> SanitizedImage:
    if declared_mime_type not in _SAFE_IMAGE_MIMES:
        raise ModelProviderError(ModelErrorCode.IMAGE_INPUT_INVALID)
    image, actual_mime = _decode_image(
        content,
        max_bytes=MAX_REFERENCE_BYTES,
        max_pixels=MAX_REFERENCE_PIXELS,
        max_edge=MAX_REFERENCE_EDGE,
        error_code=ModelErrorCode.IMAGE_INPUT_INVALID,
    )
    if actual_mime != declared_mime_type:
        raise ModelProviderError(ModelErrorCode.IMAGE_INPUT_INVALID)
    cleaned = _encode_png(image)
    return SanitizedImage(
        content=cleaned,
        mime_type="image/png",
        width=image.width,
        height=image.height,
        sha256=hashlib.sha256(cleaned).hexdigest(),
    )


Resolver = Callable[[str], tuple[str, ...]]


def _default_resolver(host: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(item[4][0])
                for item in socket.getaddrinfo(
                    host,
                    443,
                    type=socket.SOCK_STREAM,
                )
            }
        )
    )


def _require_public_ips(values: Iterable[str]) -> None:
    parsed = tuple(ipaddress.ip_address(value) for value in values)
    if not parsed or any(not address.is_global for address in parsed):
        raise ModelProviderError(ModelErrorCode.IMAGE_OUTPUT_INVALID)


def _validated_output_url(url: str, resolver: Resolver) -> str:
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError
        try:
            _require_public_ips((parsed.hostname,))
        except ValueError:
            _require_public_ips(resolver(parsed.hostname))
        return parsed.geturl()
    except (
        OSError,
        UnicodeError,
        ValueError,
        ModelProviderError,
    ):
        raise ModelProviderError(ModelErrorCode.IMAGE_OUTPUT_INVALID) from None


def _validate_connected_peer(response: httpx.Response) -> None:
    stream = response.extensions.get("network_stream")
    if stream is None:
        return
    try:
        peer = stream.get_extra_info("server_addr")
        if peer is None:
            peer = stream.get_extra_info("peername")
        if peer is not None:
            _require_public_ips((str(peer[0]),))
    except (AttributeError, IndexError, TypeError, ValueError):
        raise ModelProviderError(ModelErrorCode.IMAGE_OUTPUT_INVALID) from None


class QianwenCoverImageAdapter:
    capabilities = frozenset({Capability.IMAGE})
    status = AdapterStatus.EXPERIMENTAL

    def __init__(
        self,
        *,
        api_key: SecretStr,
        region: QianwenRegion,
        provider_workspace_id: str,
        prepared_images: tuple[QianwenPreparedImage, ...] = (),
        model_id: str = QIANWEN_IMAGE_MODEL_ID,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver = _default_resolver,
        timeout_seconds: float = 120.0,
    ) -> None:
        catalog = get_catalog_entry("qianwen", model_id)
        if (
            Capability.IMAGE not in catalog.capabilities
            or region not in catalog.available_regions
        ):
            raise ValueError("unsupported Qianwen image configuration")
        self._api_key = api_key
        self._region = region
        self._endpoint = build_qianwen_image_endpoint(
            region,
            provider_workspace_id,
        )
        self._model_id = model_id
        self._contract_version = catalog.contract_version
        self._prepared = {item.asset_id: item for item in prepared_images}
        if len(self._prepared) != len(prepared_images):
            raise ValueError("prepared image asset IDs must be unique")
        self._transport = transport
        self._resolver = resolver
        self._timeout = httpx.Timeout(timeout_seconds)
        self.last_metadata: ImageGenerationMetadata | None = None

    def bind_prepared_images(
        self,
        images: tuple[QianwenPreparedImage, ...],
    ) -> None:
        prepared = {item.asset_id: item for item in images}
        if len(prepared) != len(images):
            raise ValueError("prepared image asset IDs must be unique")
        self._prepared = prepared

    async def generate_layer(self, request: ImageModelRequest) -> Image.Image:
        images = self._resolve_images(request)
        parameters = self._parameters(request)
        self._validate_output_size(request)
        payload = self._payload(request, images, parameters)
        started = time.monotonic()
        error_code: ModelErrorCode | None = None
        provider_request_id: str | None = None
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=self._timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            try:
                response = await client.post(
                    self._endpoint,
                    headers={
                        "Authorization": (
                            f"Bearer {self._api_key.get_secret_value()}"
                        ),
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            except (httpx.TimeoutException, httpx.RequestError):
                error_code = ModelErrorCode.PROVIDER_OUTCOME_UNKNOWN
                self._log(
                    started,
                    error_code,
                    input_count=len(images),
                )
                raise ModelProviderError(error_code) from None

            provider_request_id = self._request_id(response)
            error_code = self._http_error(response.status_code)
            if error_code is not None:
                self._log(
                    started,
                    error_code,
                    input_count=len(images),
                    provider_request_id=provider_request_id,
                )
                raise ModelProviderError(
                    error_code,
                    provider_request_id=provider_request_id,
                )
            try:
                output_url, width, height = self._parse_response(
                    response,
                    request,
                )
                image = await self._download_output(
                    client,
                    output_url,
                    expected_size=(width, height),
                )
            except ModelProviderError as error:
                self._log(
                    started,
                    error.code,
                    input_count=len(images),
                    provider_request_id=provider_request_id,
                )
                raise

        seed = parameters.get("seed")
        self.last_metadata = ImageGenerationMetadata(
            provider_request_id=provider_request_id,
            seed=seed if isinstance(seed, int) else None,
            width=image.width,
            height=image.height,
            input_image_count=len(images),
        )
        self._log(
            started,
            None,
            input_count=len(images),
            provider_request_id=provider_request_id,
            width=image.width,
            height=image.height,
        )
        return image

    def _resolve_images(
        self,
        request: ImageModelRequest,
    ) -> tuple[QianwenPreparedImage, ...]:
        if len(request.references) > 3:
            raise ModelProviderError(ModelErrorCode.IMAGE_INPUT_INVALID)
        selected: list[QianwenPreparedImage] = []
        for reference in request.references:
            item = self._prepared.get(reference.asset_id)
            if item is None or item.purpose is not reference.purpose:
                raise ModelProviderError(ModelErrorCode.IMAGE_INPUT_INVALID)
            selected.append(item)
        if set(self._prepared) != {item.asset_id for item in selected}:
            raise ModelProviderError(ModelErrorCode.IMAGE_INPUT_INVALID)
        if not set(request.locked_reference_ids) <= {
            item.asset_id for item in selected
        }:
            raise ModelProviderError(ModelErrorCode.IMAGE_INPUT_INVALID)
        return tuple(selected)

    @staticmethod
    def _parameters(request: ImageModelRequest) -> dict[str, object]:
        allowed = {"seed", "negative_prompt"}
        if set(request.parameters) - allowed:
            raise ModelProviderError(ModelErrorCode.IMAGE_INPUT_INVALID)
        result: dict[str, object] = {
            "n": 1,
            "prompt_extend": False,
            "size": f"{request.size.width}*{request.size.height}",
            "watermark": False,
        }
        if "seed" in request.parameters:
            seed = request.parameters["seed"]
            if (
                not isinstance(seed, int)
                or isinstance(seed, bool)
                or not 0 <= seed <= 2_147_483_647
            ):
                raise ModelProviderError(ModelErrorCode.IMAGE_INPUT_INVALID)
            result["seed"] = seed
        if "negative_prompt" in request.parameters:
            negative = request.parameters["negative_prompt"]
            if not isinstance(negative, str) or len(negative) > 500:
                raise ModelProviderError(ModelErrorCode.IMAGE_INPUT_INVALID)
            result["negative_prompt"] = negative
        return result

    @staticmethod
    def _validate_output_size(request: ImageModelRequest) -> None:
        pixels = request.size.width * request.size.height
        if not 512 * 512 <= pixels <= 2048 * 2048:
            raise ModelProviderError(ModelErrorCode.IMAGE_INPUT_INVALID)

    def _payload(
        self,
        request: ImageModelRequest,
        images: tuple[QianwenPreparedImage, ...],
        parameters: dict[str, object],
    ) -> dict[str, object]:
        content: list[dict[str, str]] = [
            {"image": image.data_url()} for image in images
        ]
        content.append(
            {
                "text": (
                    f"{request.policy}\n\n"
                    f"Untrusted creative data:\n{request.prompt}"
                )
            }
        )
        return {
            "model": self._model_id,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": content,
                    }
                ]
            },
            "parameters": parameters,
        }

    @staticmethod
    def _http_error(status_code: int) -> ModelErrorCode | None:
        if status_code in {401, 403}:
            return ModelErrorCode.AUTHENTICATION_FAILED
        if status_code == 429:
            return ModelErrorCode.RATE_LIMITED
        if status_code >= 500:
            return ModelErrorCode.PROVIDER_UNAVAILABLE
        if status_code >= 400:
            return ModelErrorCode.IMAGE_INPUT_INVALID
        return None

    @staticmethod
    def _request_id(response: httpx.Response) -> str | None:
        value = response.headers.get("x-request-id")
        if value is None:
            try:
                candidate = response.json().get("request_id")
            except (json.JSONDecodeError, AttributeError):
                candidate = None
            value = candidate if isinstance(candidate, str) else None
        if value is None or _REQUEST_ID.fullmatch(value) is None:
            return None
        return value

    @staticmethod
    def _parse_response(
        response: httpx.Response,
        request: ImageModelRequest,
    ) -> tuple[str, int, int]:
        try:
            envelope = response.json()
            output = envelope["output"]
            choices = output["choices"]
            if not isinstance(choices, list) or len(choices) != 1:
                raise TypeError
            choice = choices[0]
            if (
                not isinstance(choice, dict)
                or choice.get("finish_reason") != "stop"
            ):
                raise TypeError
            message = choice["message"]
            content = message["content"]
            if (
                not isinstance(message, dict)
                or message.get("role") != "assistant"
                or not isinstance(content, list)
                or len(content) != 1
                or not isinstance(content[0], dict)
                or set(content[0]) != {"image"}
                or not isinstance(content[0]["image"], str)
            ):
                raise TypeError
            usage = envelope["usage"]
            width = usage["width"]
            height = usage["height"]
            if (
                not isinstance(usage, dict)
                or usage.get("image_count") != 1
                or not isinstance(width, int)
                or isinstance(width, bool)
                or not isinstance(height, int)
                or isinstance(height, bool)
                or (width, height)
                != (request.size.width, request.size.height)
            ):
                raise TypeError
            return content[0]["image"], width, height
        except (
            json.JSONDecodeError,
            KeyError,
            TypeError,
        ):
            raise ModelProviderError(
                ModelErrorCode.IMAGE_OUTPUT_INVALID
            ) from None

    async def _download_output(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        expected_size: tuple[int, int],
    ) -> Image.Image:
        current = _validated_output_url(url, self._resolver)
        for redirect_count in range(MAX_REDIRECTS + 1):
            try:
                async with client.stream("GET", current) as response:
                    _validate_connected_peer(response)
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if location is None or redirect_count >= MAX_REDIRECTS:
                            raise ModelProviderError(
                                ModelErrorCode.IMAGE_OUTPUT_INVALID
                            )
                        current = _validated_output_url(
                            urljoin(current, location),
                            self._resolver,
                        )
                        continue
                    if response.status_code in {403, 404, 410}:
                        raise ModelProviderError(
                            ModelErrorCode.IMAGE_RESULT_EXPIRED
                        )
                    if response.status_code != 200:
                        raise ModelProviderError(
                            ModelErrorCode.IMAGE_OUTPUT_INVALID
                        )
                    content_type = response.headers.get(
                        "content-type",
                        "",
                    ).split(";", 1)[0].strip().lower()
                    if content_type not in _SAFE_IMAGE_MIMES:
                        raise ModelProviderError(
                            ModelErrorCode.IMAGE_OUTPUT_INVALID
                        )
                    length = response.headers.get("content-length")
                    if length is not None and int(length) > MAX_OUTPUT_BYTES:
                        raise ModelProviderError(
                            ModelErrorCode.IMAGE_OUTPUT_INVALID
                        )
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > MAX_OUTPUT_BYTES:
                            raise ModelProviderError(
                                ModelErrorCode.IMAGE_OUTPUT_INVALID
                            )
                        chunks.append(chunk)
                    image, actual_mime = _decode_image(
                        b"".join(chunks),
                        max_bytes=MAX_OUTPUT_BYTES,
                        max_pixels=2048 * 2048,
                        max_edge=None,
                        error_code=ModelErrorCode.IMAGE_OUTPUT_INVALID,
                    )
                    if (
                        actual_mime != content_type
                        or image.size != expected_size
                    ):
                        raise ModelProviderError(
                            ModelErrorCode.IMAGE_OUTPUT_INVALID
                        )
                    cleaned = _encode_png(image)
                    decoded = Image.open(BytesIO(cleaned))
                    decoded.load()
                    return decoded.convert("RGB")
            except ModelProviderError:
                raise
            except (
                httpx.TimeoutException,
                httpx.RequestError,
                OSError,
                ValueError,
            ):
                raise ModelProviderError(
                    ModelErrorCode.IMAGE_OUTPUT_INVALID
                ) from None
        raise ModelProviderError(ModelErrorCode.IMAGE_OUTPUT_INVALID)

    def _log(
        self,
        started: float,
        error_code: ModelErrorCode | None,
        *,
        input_count: int,
        provider_request_id: str | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        emit_log(
            _logger,
            event="model.provider.image_attempt",
            message_code="MODEL_PROVIDER_IMAGE_ATTEMPT",
            provider="qianwen",
            model_id=self._model_id,
            model_contract_version=self._contract_version,
            region=self._region.value,
            provider_request_id=provider_request_id,
            input_count=input_count,
            output_count=1 if error_code is None else 0,
            image_width=width,
            image_height=height,
            latency_ms=round((time.monotonic() - started) * 1000, 3),
            attempt=1,
            error_code=error_code.value if error_code is not None else None,
        )
