from app.modules.imports.ocr_adapters import VisionRecognition
from app.modules.risk_rag.scanner import (
    OcrRegion,
    OcrResult,
    OcrStatus,
)


def vision_recognition_to_ocr(
    recognition: VisionRecognition,
) -> OcrResult:
    regions = tuple(
        OcrRegion(
            text=item.text,
            bbox=(
                item.region.x,
                item.region.y,
                item.region.width,
                item.region.height,
            ),
            confidence=(
                0
                if recognition.confidence_source == "unavailable"
                else recognition.platform_confidence
            ),
        )
        for item in recognition.text_regions
    )
    return OcrResult(
        status=OcrStatus.SUCCEEDED if regions else OcrStatus.EMPTY,
        regions=regions,
        confidence_source=recognition.confidence_source,
        requires_human_review=(
            recognition.requires_human_review
            or recognition.confidence_source == "unavailable"
        ),
    )
