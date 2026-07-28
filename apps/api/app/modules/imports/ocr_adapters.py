from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.modules.content.account_models import Platform


class RecognitionRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)


class RecognizedContentIdentifier(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform_content_id: str | None = None
    work_url: str | None = None
    confidence: float = Field(ge=0, le=1)
    region: RecognitionRegion


class RecognizedMetricCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=80)
    confidence: float = Field(ge=0, le=1)
    region: RecognitionRegion


class RecognizedTextRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2_000)
    region: RecognitionRegion
    rotate_rect: tuple[float, float, float, float, float] | None = None


class VisionRecognition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Literal["douyin", "xiaohongshu"]
    platform_confidence: float = Field(ge=0, le=1)
    content_identifier: RecognizedContentIdentifier | None = None
    metric_candidates: list[RecognizedMetricCandidate] = Field(max_length=100)
    text_regions: tuple[RecognizedTextRegion, ...] = Field(
        default=(), max_length=1_000
    )
    unmapped_text: tuple[str, ...] = Field(default=(), max_length=1_000)
    confidence_source: Literal["mock", "unavailable"] = "mock"
    requires_human_review: bool = False
    model_id: str = "mock-v1"
    contract_version: str = "mock-vision-v1"
    provider_request_id: str | None = None
    image_tokens: int | None = Field(default=None, ge=0)


class VisionAdapter(Protocol):
    def recognize(self, image: bytes, mime_type: str) -> VisionRecognition: ...


class MockVisionAdapter:
    def __init__(self, platform: Platform) -> None:
        self._platform = platform

    def recognize(self, image: bytes, mime_type: str) -> VisionRecognition:
        if not image or not mime_type.startswith("image/"):
            raise ValueError("mock adapter requires an image")
        metric_key = (
            "views" if self._platform == Platform.DOUYIN else "impressions"
        )
        return VisionRecognition.model_validate(
            {
                "platform": self._platform.value,
                "platform_confidence": 0.99,
                "content_identifier": {
                    "platform_content_id": f"MOCK-{self._platform.value}-001",
                    "work_url": None,
                    "confidence": 0.95,
                    "region": {
                        "x": 0.05,
                        "y": 0.05,
                        "width": 0.8,
                        "height": 0.1,
                    },
                },
                "metric_candidates": [
                    {
                        "key": metric_key,
                        "value": "1000",
                        "confidence": 0.96,
                        "region": {
                            "x": 0.1,
                            "y": 0.4,
                            "width": 0.2,
                            "height": 0.1,
                        },
                    }
                ],
            }
        )


class UnavailableVisionAdapter:
    def recognize(self, image: bytes, mime_type: str) -> VisionRecognition:
        raise RuntimeError("vision adapter is not configured")


def get_vision_adapter(platform: Platform) -> VisionAdapter:
    if get_settings().app_mock_mode:
        return MockVisionAdapter(platform)
    return UnavailableVisionAdapter()
