import base64
from io import BytesIO
import json
import logging
from uuid import uuid4

import httpx
from PIL import Image, PngImagePlugin
from pydantic import SecretStr
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.security import WorkspaceContext
from app.modules.content.account_models import Platform
from app.modules.imports.ocr_adapters import VisionRecognition
from app.modules.models.adapters.qianwen import ModelErrorCode, ModelProviderError
from app.modules.models.adapters.qianwen_vision import QianwenVisionAdapter
from app.modules.models.capabilities import Capability
from app.modules.models.capabilities import AdapterStatus
from app.modules.models.catalog import (
    QIANWEN_OCR_MODEL_ID,
    QianwenRegion,
    build_qianwen_ocr_endpoint,
    get_catalog_entry,
)
from app.modules.models.config_service import ModelConfigService, SecretCipher
from app.modules.models.usage import (
    UsageAttemptHandle,
    UsageAttemptOutcome,
    UsageEstimate,
)
from app.modules.workspace.models import Workspace


def _image(
    *,
    image_format: str = "PNG",
    size: tuple[int, int] = (200, 100),
    metadata: bool = False,
) -> bytes:
    output = BytesIO()
    image = Image.new("RGB", size, color=(230, 240, 250))
    kwargs: dict[str, object] = {}
    if metadata and image_format == "PNG":
        info = PngImagePlugin.PngInfo()
        info.add_text("Comment", "sensitive-metadata-never-send")
        kwargs["pnginfo"] = info
    image.save(output, format=image_format, **kwargs)
    return output.getvalue()


def _response(
    words: list[dict[str, object]],
    *,
    status_code: int = 200,
) -> httpx.Response:
    if status_code != 200:
        return httpx.Response(
            status_code,
            json={"message": "provider-sensitive-body-never-expose"},
        )
    payload = {
            "request_id": "req-ocr-synthetic",
            "output": {
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"ocr_result": {"words_info": words}}
                            ]
                        }
                    }
                ]
            },
            "usage": {
                "input_tokens": 30,
                "output_tokens": 10,
                "total_tokens": 40,
                "image_tokens": 22,
            },
        }
    return httpx.Response(
        200,
        content=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
    )


def _adapter(
    handler,
    *,
    platform: Platform = Platform.DOUYIN,
    usage_governor=None,
) -> QianwenVisionAdapter:
    return QianwenVisionAdapter(
        workspace_id=uuid4(),
        model_config_id=uuid4(),
        expected_platform=platform,
        region=QianwenRegion.CN_BEIJING,
        provider_workspace_id="llm-abcd1234",
        api_key=SecretStr("sk-synthetic-never-real"),
        model_id=QIANWEN_OCR_MODEL_ID,
        contract_version="qwen-ocr-advanced-v1",
        allowed_metric_labels=(
            {"播放量": "views", "点赞": "likes"}
            if platform is Platform.DOUYIN
            else {"曝光量": "impressions", "阅读量": "views"}
        ),
        transport=httpx.MockTransport(handler),
        sleeper=lambda _: None,
        usage_governor=usage_governor,
    )


class _UsageRecorder:
    def __init__(self) -> None:
        self.started: list[tuple[int, UsageEstimate]] = []
        self.finished: list[tuple[UsageAttemptOutcome, UsageEstimate | None]] = []

    def begin_attempt(
        self, number: int, estimate: UsageEstimate
    ) -> UsageAttemptHandle:
        self.started.append((number, estimate))
        return UsageAttemptHandle(
            analytics_eligible=False,
            reservation_id=None,
            attempt_id=uuid4(),
            lease_key=None,
            lease_token=None,
            estimate=estimate,
            estimated_cost_microunits=0,
            provider_attempt_number=number,
        )

    def finish_attempt(
        self,
        handle: UsageAttemptHandle,
        *,
        outcome: UsageAttemptOutcome,
        actual: UsageEstimate | None,
        latency_ms: int,
        provider_request_id: str | None = None,
        stable_error_code: str | None = None,
    ) -> None:
        assert latency_ms >= 0
        self.finished.append((outcome, actual))


def test_catalog_keeps_text_and_ocr_capabilities_separate() -> None:
    text = get_catalog_entry("qianwen", "qwen3.5-plus-2026-04-20")
    ocr = get_catalog_entry("qianwen", QIANWEN_OCR_MODEL_ID)

    assert text.capabilities == frozenset({Capability.TEXT})
    assert ocr.model_id == "qwen-vl-ocr-2025-11-20"
    assert ocr.capabilities == frozenset({Capability.VISION})
    assert ocr.protocol == "dashscope_multimodal_generation"
    assert ocr.contract_version == "qwen-ocr-advanced-v1"
    assert ocr.confidence_available is False
    assert ocr.supported_mime_types == frozenset(
        {"image/png", "image/jpeg", "image/webp"}
    )


@pytest.mark.parametrize(
    ("region", "host"),
    [
        (QianwenRegion.CN_BEIJING, "llm-abcd1234.cn-beijing.maas.aliyuncs.com"),
        (
            QianwenRegion.AP_SOUTHEAST_1,
            "llm-abcd1234.ap-southeast-1.maas.aliyuncs.com",
        ),
    ],
)
def test_native_ocr_endpoint_is_server_constructed(
    region: QianwenRegion,
    host: str,
) -> None:
    assert build_qianwen_ocr_endpoint(region, "llm-abcd1234") == (
        f"https://{host}/api/v1/services/aigc/"
        "multimodal-generation/generation"
    )


def test_official_ocr_response_is_normalized_without_fake_confidence() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _response(
            [
                {
                    "text": "播放量 12,000",
                    "location": [0, 0, 100, 0, 100, 20, 0, 20],
                    "rotate_rect": [50, 10, 100, 20, 0],
                },
                {
                    "text": "曝光量 999",
                    "location": [0, 40, 100, 40, 100, 60, 0, 60],
                    "rotate_rect": [50, 50, 100, 20, 0],
                },
            ]
        )

    result = _adapter(handler).recognize(_image(), "image/png")

    assert result.platform == "douyin"
    assert result.platform_confidence == 0
    assert result.confidence_source == "unavailable"
    assert result.requires_human_review is True
    assert result.model_id == QIANWEN_OCR_MODEL_ID
    assert result.contract_version == "qwen-ocr-advanced-v1"
    assert result.provider_request_id == "req-ocr-synthetic"
    assert result.image_tokens == 22
    assert result.metric_candidates[0].key == "views"
    assert result.metric_candidates[0].value == "12000"
    assert result.metric_candidates[0].confidence == 0
    assert result.metric_candidates[0].region.model_dump() == {
        "x": 0.0,
        "y": 0.0,
        "width": 0.5,
        "height": 0.2,
    }
    assert result.unmapped_text == ("曝光量 999",)

    payload = json.loads(captured[0].content)
    assert payload["model"] == QIANWEN_OCR_MODEL_ID
    assert payload["parameters"]["ocr_options"]["task"] == "advanced_recognition"
    assert payload["input"]["messages"][0]["content"][0]["min_pixels"] == 3072
    assert (
        payload["input"]["messages"][0]["content"][0]["max_pixels"]
        == 8_388_608
    )
    data_url = payload["input"]["messages"][0]["content"][0]["image"]
    assert data_url.startswith("data:image/png;base64,")
    sent = base64.b64decode(data_url.partition(",")[2])
    with Image.open(BytesIO(sent)) as sanitized:
        assert sanitized.info.get("Comment") is None


def test_ocr_http_attempt_is_governed_with_image_and_token_usage() -> None:
    usage = _UsageRecorder()
    adapter = _adapter(
        lambda request: _response(
            [
                {
                    "text": "播放量 12",
                    "location": [0, 0, 100, 0, 100, 20, 0, 20],
                    "rotate_rect": [50, 10, 100, 20, 0],
                }
            ]
        ),
        usage_governor=usage,
    )

    adapter.recognize(_image(), "image/png")

    assert len(usage.started) == 1
    assert usage.started[0][1].ocr_images == 1
    assert usage.started[0][1].input_images == 1
    assert usage.finished == [
        (
            UsageAttemptOutcome.SUCCEEDED,
            UsageEstimate(
                input_tokens=30,
                output_tokens=10,
                ocr_images=1,
                input_images=1,
            ),
        )
    ]
@pytest.mark.parametrize(
    ("image", "mime_type", "code"),
    [
        (b"", "image/png", ModelErrorCode.IMAGE_INVALID),
        (_image(), "image/jpeg", ModelErrorCode.IMAGE_INVALID),
        (b"<svg/>", "image/svg+xml", ModelErrorCode.IMAGE_INVALID),
        (_image(image_format="GIF"), "image/gif", ModelErrorCode.IMAGE_INVALID),
        (b"not-an-image", "image/png", ModelErrorCode.IMAGE_INVALID),
    ],
)
def test_image_validation_rejects_unsafe_or_mismatched_input(
    image: bytes,
    mime_type: str,
    code: ModelErrorCode,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response([])

    with pytest.raises(ModelProviderError) as caught:
        _adapter(handler).recognize(image, mime_type)

    assert caught.value.code is code
    assert calls == 0


def test_pixel_limit_is_checked_after_decode_before_network() -> None:
    image = _image(size=(4096, 4096))
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response([])

    with pytest.raises(ModelProviderError) as caught:
        _adapter(handler).recognize(image, "image/png")

    assert caught.value.code is ModelErrorCode.IMAGE_TOO_LARGE
    assert calls == 0


@pytest.mark.parametrize(
    "location",
    [
        [-1, 0, 10, 0, 10, 10, 0, 10],
        [0, 0, 201, 0, 201, 10, 0, 10],
        [1, 1, 1, 1, 1, 1, 1, 1],
        [0, 0, float("nan"), 0, 10, 10, 0, 10],
    ],
)
def test_invalid_provider_coordinates_are_rejected(location: list[float]) -> None:
    adapter = _adapter(
        lambda request: _response(
            [
                {
                    "text": "播放量 1",
                    "location": location,
                    "rotate_rect": [5, 5, 10, 10, 0],
                }
            ]
        )
    )

    with pytest.raises(ModelProviderError) as caught:
        adapter.recognize(_image(), "image/png")

    assert caught.value.code is ModelErrorCode.OCR_INVALID_RESPONSE


@pytest.mark.parametrize("body", [{}, {"output": {}}, {"choices": []}])
def test_non_official_or_markdown_like_response_is_rejected(body: object) -> None:
    adapter = _adapter(lambda request: httpx.Response(200, json=body))

    with pytest.raises(ModelProviderError) as caught:
        adapter.recognize(_image(), "image/png")

    assert caught.value.code is ModelErrorCode.OCR_INVALID_RESPONSE


def test_retryable_provider_failure_has_two_attempts_maximum() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response([], status_code=503)

    with pytest.raises(ModelProviderError):
        _adapter(handler).recognize(_image(), "image/png")

    assert calls == 2


def test_ocr_logs_do_not_include_image_or_data_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    adapter = _adapter(lambda request: _response([]))

    adapter.recognize(_image(metadata=True), "image/png")

    rendered = caplog.text
    assert "data:image/" not in rendered
    assert "sensitive-metadata-never-send" not in rendered
    assert "sk-synthetic-never-real" not in rendered


def test_vision_result_schema_rejects_raw_provider_response() -> None:
    with pytest.raises(Exception):
        VisionRecognition.model_validate(
            {
                "platform": "douyin",
                "platform_confidence": 0,
                "metric_candidates": [],
                "raw_provider_response": {"secret": "not allowed"},
            }
        )


def test_qianwen_ocr_maps_to_risk_input_with_forced_human_review() -> None:
    from app.modules.risk_rag.ocr import vision_recognition_to_ocr

    recognition = _adapter(
        lambda request: _response(
            [
                {
                    "text": "高风险合成词",
                    "location": [10, 20, 110, 20, 110, 40, 10, 40],
                    "rotate_rect": [60, 30, 100, 20, 0],
                }
            ]
        )
    ).recognize(_image(), "image/png")

    ocr = vision_recognition_to_ocr(recognition)

    assert ocr.status == "succeeded"
    assert ocr.regions[0].confidence == 0
    assert ocr.confidence_source == "unavailable"
    assert ocr.requires_human_review is True


def test_workspace_binding_is_frozen_and_cross_workspace_config_is_rejected() -> None:
    from app.modules.imports.vision_binding import (
        create_bound_vision_adapter,
        resolve_vision_binding,
    )
    from app.modules.metrics.models import ContentType

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    cipher = SecretCipher("synthetic-vision-binding-key")
    with Session(engine, expire_on_commit=False) as session:
        workspace = Workspace(name="vision-workspace")
        other = Workspace(name="other-vision-workspace")
        session.add_all([workspace, other])
        session.flush()
        context = WorkspaceContext(
            workspace_id=workspace.id,
            member_id=None,
            role="admin",
        )
        config = ModelConfigService(
            session, context, cipher=cipher
        ).save(
            provider="qianwen",
            model_id=QIANWEN_OCR_MODEL_ID,
            capabilities=frozenset({Capability.VISION}),
            status=AdapterStatus.EXPERIMENTAL,
            api_key="sk-synthetic-never-real",
            region=QianwenRegion.CN_BEIJING,
            provider_workspace_id="llm-abcd1234",
        )
        binding = resolve_vision_binding(
            session,
            context,
            platform=Platform.DOUYIN,
            content_type=ContentType.VIDEO,
            cipher=cipher,
            mock_mode=False,
        )
        assert binding.model_config_id == config.id
        assert binding.metric_labels["播放量"] == "views"
        adapter = create_bound_vision_adapter(
            session,
            workspace_id=workspace.id,
            expected_platform=Platform.DOUYIN,
            binding=binding,
            cipher=cipher,
            mock_mode=False,
            transport=httpx.MockTransport(
                lambda request: _response(
                    [
                        {
                            "text": "播放量 1",
                            "location": [0, 0, 20, 0, 20, 20, 0, 20],
                            "rotate_rect": [10, 10, 20, 20, 0],
                        }
                    ]
                )
            ),
        )
        assert adapter.recognize(_image(), "image/png").platform == "douyin"

        with pytest.raises(ValueError, match="frozen"):
            create_bound_vision_adapter(
                session,
                workspace_id=other.id,
                expected_platform=Platform.DOUYIN,
                binding=binding,
                cipher=cipher,
                mock_mode=False,
            )
