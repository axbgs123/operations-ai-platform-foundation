import asyncio
from io import BytesIO
import logging
from uuid import UUID, uuid4

import httpx
from PIL import Image, PngImagePlugin
from pydantic import SecretStr
import pytest

from app.modules.generation.cover_models import (
    CoverReference,
    CoverSize,
    ReferencePurpose,
)
from app.modules.generation.cover_service import (
    IMAGE_LAYER_POLICY,
    ImageModelRequest,
)
from app.modules.models.adapters.qianwen import (
    ModelErrorCode,
    ModelProviderError,
)
from app.modules.models.adapters.qianwen_image import (
    QIANWEN_COVER_CONTRACT_VERSION,
    QianwenCoverImageAdapter,
    QianwenPreparedImage,
    sanitize_reference_image,
)
from app.modules.models.catalog import (
    QIANWEN_IMAGE_MODEL_ID,
    ProviderProtocol,
    QianwenRegion,
    build_qianwen_image_endpoint,
    get_catalog_entry,
)


MODEL_ID = "qwen-image-2.0-pro-2026-06-22"
WORKSPACE_ID = "llm-synthetic1234"
API_KEY = "sk-synthetic-never-real"
PUBLIC_IP = "93.184.216.34"


def _png(
    *,
    size: tuple[int, int] = (512, 512),
    color: str = "#235789",
    metadata: bool = False,
) -> bytes:
    output = BytesIO()
    info = None
    if metadata:
        info = PngImagePlugin.PngInfo()
        info.add_text("Comment", "SYNTHETIC-GPS-LIKE-METADATA")
    Image.new("RGB", size, color).save(output, "PNG", pnginfo=info)
    return output.getvalue()


def _prepared(
    *,
    asset_id: UUID | None = None,
    purpose: ReferencePurpose = ReferencePurpose.STYLE,
    size: tuple[int, int] = (512, 512),
) -> QianwenPreparedImage:
    identifier = asset_id or uuid4()
    return QianwenPreparedImage.from_untrusted_bytes(
        asset_id=identifier,
        asset_version=3,
        purpose=purpose,
        declared_mime_type="image/png",
        content=_png(size=size, metadata=True),
    )


def _request(
    *images: QianwenPreparedImage,
    size: tuple[int, int] = (512, 512),
    parameters: dict[str, object] | None = None,
) -> ImageModelRequest:
    return ImageModelRequest(
        policy=IMAGE_LAYER_POLICY,
        prompt="合成的蓝色工作台场景，主体居中，为左上角标题保留干净空间",
        size=CoverSize(width=size[0], height=size[1]),
        references=tuple(
            CoverReference(asset_id=item.asset_id, purpose=item.purpose)
            for item in images
        ),
        locked_reference_ids=tuple(
            item.asset_id
            for item in images
            if item.purpose
            in {ReferencePurpose.PERSON, ReferencePurpose.PRODUCT}
        ),
        parameters=parameters or {},
    )


def _success_envelope(
    output_url: str = "https://provider-output.example/result.png",
    *,
    width: int = 512,
    height: int = 512,
    content: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "output": {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": content or [{"image": output_url}],
                    },
                }
            ]
        },
        "usage": {"image_count": 1, "width": width, "height": height},
        "request_id": "synthetic-request-123",
    }


def _adapter(
    handler,
    *,
    images: tuple[QianwenPreparedImage, ...] = (),
    region: QianwenRegion = QianwenRegion.CN_BEIJING,
    resolver=lambda _host: (PUBLIC_IP,),
) -> QianwenCoverImageAdapter:
    return QianwenCoverImageAdapter(
        api_key=SecretStr(API_KEY),
        region=region,
        provider_workspace_id=WORKSPACE_ID,
        prepared_images=images,
        transport=httpx.MockTransport(handler),
        resolver=resolver,
    )


def test_catalog_pins_exact_image_snapshot_and_contract() -> None:
    entry = get_catalog_entry("qianwen", MODEL_ID)

    assert QIANWEN_IMAGE_MODEL_ID == MODEL_ID
    assert entry.model_id == MODEL_ID
    assert entry.capabilities == {"image"}
    assert entry.protocol is ProviderProtocol.DASHSCOPE_MULTIMODAL_GENERATION
    assert entry.contract_version == QIANWEN_COVER_CONTRACT_VERSION
    assert entry.available_regions == {
        QianwenRegion.CN_BEIJING,
        QianwenRegion.AP_SOUTHEAST_1,
    }
    assert entry.max_reference_images == 3
    assert entry.max_output_images == 1
    assert entry.upstream_snapshot_immutable is True


@pytest.mark.parametrize(
    ("region", "hostname"),
    [
        (
            QianwenRegion.CN_BEIJING,
            f"{WORKSPACE_ID}.cn-beijing.maas.aliyuncs.com",
        ),
        (
            QianwenRegion.AP_SOUTHEAST_1,
            f"{WORKSPACE_ID}.ap-southeast-1.maas.aliyuncs.com",
        ),
    ],
)
def test_image_endpoint_is_server_constructed_for_each_region(
    region: QianwenRegion,
    hostname: str,
) -> None:
    endpoint = build_qianwen_image_endpoint(region, WORKSPACE_ID)

    assert endpoint == (
        f"https://{hostname}/api/v1/services/aigc/"
        "multimodal-generation/generation"
    )
    with pytest.raises(ValueError):
        build_qianwen_image_endpoint(
            region,
            "https://attacker.invalid/api",
        )


def test_text_to_image_payload_is_single_turn_and_fixed_to_one_output() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                headers={"Content-Type": "image/png"},
                content=_png(),
            )
        return httpx.Response(200, json=_success_envelope())

    adapter = _adapter(handler)
    image = asyncio.run(adapter.generate_layer(_request()))
    payload = requests[0].read()
    parsed = __import__("json").loads(payload)

    assert image.size == (512, 512)
    assert len(requests) == 2
    assert requests[0].headers["Authorization"] == f"Bearer {API_KEY}"
    assert parsed["model"] == MODEL_ID
    assert parsed["input"]["messages"] == [
        {
            "role": "user",
            "content": [
                {
                    "text": (
                        "Only generate background and subject pixels. "
                        "Do not render text, letters, numbers, logos, brand "
                        "marks, or watermarks. Keep clean negative space for "
                        "the programmatic title area.\n\n"
                        "Untrusted creative data:\n"
                        "合成的蓝色工作台场景，主体居中，为左上角标题保留干净空间"
                    )
                }
            ],
        }
    ]
    assert parsed["parameters"] == {
        "n": 1,
        "prompt_extend": False,
        "size": "512*512",
        "watermark": False,
    }


def test_edit_payload_uses_one_to_three_clean_images_in_frozen_order() -> None:
    first = _prepared(purpose=ReferencePurpose.PERSON)
    second = _prepared(purpose=ReferencePurpose.PRODUCT)
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                headers={"Content-Type": "image/png"},
                content=_png(),
            )
        captured.append(__import__("json").loads(request.read()))
        return httpx.Response(200, json=_success_envelope())

    adapter = _adapter(handler, images=(first, second))
    asyncio.run(adapter.generate_layer(_request(first, second)))

    content = captured[0]["input"]["messages"][0]["content"]
    assert len(content) == 3
    assert content[0]["image"] == first.data_url()
    assert content[1]["image"] == second.data_url()
    assert content[2]["text"].startswith("Only generate background")
    assert first.asset_id != second.asset_id


def test_reference_count_and_identity_are_checked_before_billed_call() -> None:
    images = tuple(_prepared() for _ in range(4))
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("provider must not be called")

    with pytest.raises(
        ModelProviderError,
        match=ModelErrorCode.IMAGE_INPUT_INVALID.value,
    ):
        asyncio.run(
            _adapter(handler, images=images).generate_layer(_request(*images))
        )
    assert calls == 0

    missing = _prepared()
    with pytest.raises(ModelProviderError):
        asyncio.run(_adapter(handler).generate_layer(_request(missing)))
    assert calls == 0


@pytest.mark.parametrize(
    "parameters",
    [
        {"base_url": "https://attacker.invalid"},
        {"model": "latest"},
        {"n": 6},
        {"watermark": True},
        {"prompt_extend": True},
        {"unknown": "value"},
        {"seed": -1},
        {"seed": 2_147_483_648},
    ],
)
def test_provider_parameters_use_a_strict_allowlist(
    parameters: dict[str, object],
) -> None:
    with pytest.raises(ModelProviderError):
        asyncio.run(
            _adapter(lambda _request: httpx.Response(500)).generate_layer(
                _request(parameters=parameters)
            )
        )


def test_seed_and_negative_prompt_are_the_only_custom_overrides() -> None:
    payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                headers={"Content-Type": "image/png"},
                content=_png(),
            )
        payloads.append(__import__("json").loads(request.read()))
        return httpx.Response(200, json=_success_envelope())

    adapter = _adapter(handler)
    asyncio.run(
        adapter.generate_layer(
            _request(
                parameters={
                    "seed": 20260729,
                    "negative_prompt": "文字，字母，数字，Logo，水印",
                }
            )
        )
    )

    assert payloads[0]["parameters"]["seed"] == 20260729
    assert (
        payloads[0]["parameters"]["negative_prompt"]
        == "文字，字母，数字，Logo，水印"
    )
    assert adapter.last_metadata is not None
    assert adapter.last_metadata.seed == 20260729
    assert adapter.last_metadata.provider_request_id == "synthetic-request-123"


def test_reference_sanitizer_sniffs_content_and_removes_metadata() -> None:
    content = _png(metadata=True)
    cleaned = sanitize_reference_image(
        content,
        declared_mime_type="image/png",
    )

    assert cleaned.mime_type == "image/png"
    assert cleaned.width == 512
    assert cleaned.height == 512
    assert cleaned.content != content
    decoded = Image.open(BytesIO(cleaned.content))
    assert decoded.info == {}

    with pytest.raises(ModelProviderError):
        sanitize_reference_image(
            b"<svg><script>unsafe()</script></svg>",
            declared_mime_type="image/png",
        )
    with pytest.raises(ModelProviderError):
        sanitize_reference_image(
            _png(),
            declared_mime_type="image/jpeg",
        )


def test_reference_sanitizer_rejects_oversized_dimensions_and_animated_images() -> None:
    with pytest.raises(ModelProviderError):
        sanitize_reference_image(
            _png(size=(4096, 4096)),
            declared_mime_type="image/png",
        )

    animated = BytesIO()
    frames = [
        Image.new("RGB", (64, 64), "#111111"),
        Image.new("RGB", (64, 64), "#222222"),
    ]
    frames[0].save(
        animated,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
    )
    with pytest.raises(ModelProviderError):
        sanitize_reference_image(
            animated.getvalue(),
            declared_mime_type="image/gif",
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://provider-output.example/result.png",
        "https://user:pass@provider-output.example/result.png",
        "https://provider-output.example/result.png#fragment",
        "https://127.0.0.1/result.png",
        "https://169.254.169.254/latest/meta-data",
        "https://10.0.0.1/result.png",
    ],
)
def test_provider_output_url_rejects_unsafe_targets_before_download(url: str) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_success_envelope(url))

    with pytest.raises(ModelProviderError):
        asyncio.run(_adapter(handler).generate_layer(_request()))
    assert calls == 1


def test_provider_output_revalidates_dns_and_each_redirect() -> None:
    calls: list[str] = []

    def resolver(host: str) -> tuple[str, ...]:
        if host == "private.example":
            return ("10.1.2.3",)
        return (PUBLIC_IP,)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.method == "POST":
            return httpx.Response(200, json=_success_envelope())
        return httpx.Response(
            302,
            headers={"Location": "https://private.example/result.png"},
        )

    with pytest.raises(ModelProviderError):
        asyncio.run(
            _adapter(handler, resolver=resolver).generate_layer(_request())
        )
    assert calls == [
        (
            f"https://{WORKSPACE_ID}.cn-beijing.maas.aliyuncs.com/"
            "api/v1/services/aigc/multimodal-generation/generation"
        ),
        "https://provider-output.example/result.png",
    ]


@pytest.mark.parametrize(
    ("content_type", "content"),
    [
        ("text/html", b"<html>synthetic error</html>"),
        ("application/json", b'{"error":"synthetic"}'),
        ("image/png", b"not-an-image"),
    ],
)
def test_provider_output_requires_valid_static_image(
    content_type: str,
    content: bytes,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=_success_envelope())
        return httpx.Response(
            200,
            headers={"Content-Type": content_type},
            content=content,
        )

    with pytest.raises(
        ModelProviderError,
        match=ModelErrorCode.IMAGE_OUTPUT_INVALID.value,
    ):
        asyncio.run(_adapter(handler).generate_layer(_request()))


def test_provider_output_is_reencoded_to_metadata_free_png() -> None:
    source = _png(metadata=True)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=_success_envelope())
        return httpx.Response(
            200,
            headers={"Content-Type": "image/png"},
            content=source,
        )

    image = asyncio.run(_adapter(handler).generate_layer(_request()))
    output = BytesIO()
    image.save(output, "PNG")

    assert image.info == {}
    assert b"SYNTHETIC-GPS-LIKE-METADATA" not in output.getvalue()


def test_multiple_provider_results_or_wrong_dimensions_are_rejected() -> None:
    def multiple(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json=_success_envelope(
                    content=[
                        {"image": "https://provider-output.example/one.png"},
                        {"image": "https://provider-output.example/two.png"},
                    ]
                ),
            )
        raise AssertionError("output download must not start")

    with pytest.raises(ModelProviderError):
        asyncio.run(_adapter(multiple).generate_layer(_request()))

    def wrong_size(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json=_success_envelope(width=1024, height=1024),
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "image/png"},
            content=_png(size=(1024, 1024)),
        )

    with pytest.raises(ModelProviderError):
        asyncio.run(_adapter(wrong_size).generate_layer(_request()))


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadTimeout("synthetic timeout"),
        httpx.ConnectError("synthetic disconnect"),
    ],
)
def test_uncertain_provider_outcome_is_not_retried(
    failure: httpx.RequestError,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise failure

    with pytest.raises(
        ModelProviderError,
        match=ModelErrorCode.PROVIDER_OUTCOME_UNKNOWN.value,
    ):
        asyncio.run(_adapter(handler).generate_layer(_request()))
    assert attempts == 1


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_http_failures_are_never_automatically_retried(status: int) -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            status,
            json={"code": "SyntheticFailure", "message": API_KEY},
        )

    with pytest.raises(ModelProviderError) as captured:
        asyncio.run(_adapter(handler).generate_layer(_request()))

    assert attempts == 1
    assert API_KEY not in str(captured.value)


def test_logs_and_metadata_never_contain_sensitive_payloads(
    caplog: pytest.LogCaptureFixture,
) -> None:
    prompt = "SYNTHETIC_PRIVATE_PROMPT"
    temporary_url = "https://provider-output.example/signed-secret.png"
    image = _prepared()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json=_success_envelope(temporary_url),
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "image/png"},
            content=_png(),
        )

    request = _request(image).model_copy(update={"prompt": prompt})
    with caplog.at_level(logging.INFO):
        adapter = _adapter(handler, images=(image,))
        asyncio.run(adapter.generate_layer(request))

    logs = caplog.text
    assert "model.provider.image_attempt" in logs
    for secret in (
        API_KEY,
        WORKSPACE_ID,
        prompt,
        temporary_url,
        image.data_url(),
    ):
        assert secret not in logs
    assert adapter.last_metadata is not None
    serialized = adapter.last_metadata.model_dump_json()
    assert temporary_url not in serialized
    assert API_KEY not in serialized
