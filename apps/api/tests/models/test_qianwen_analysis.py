from typing import cast

import pytest

from app.modules.analysis.schemas import AnalysisReport, MockAnalysisAdapter
from app.modules.models.capabilities import ModelRequest
from tests.analysis.test_analysis_report import evidence_bundle


class RecordingProvider:
    def __init__(self, result: AnalysisReport) -> None:
        self.result = result
        self.requests: list[ModelRequest[AnalysisReport]] = []

    async def generate_structured(
        self,
        request: ModelRequest[AnalysisReport],
    ) -> AnalysisReport:
        self.requests.append(request)
        return self.result


def test_analysis_adapter_sends_only_text_evidence_and_preserves_validator() -> None:
    from app.modules.models.adapters.qianwen_analysis import (
        QianwenAnalysisAdapter,
    )

    bundle = evidence_bundle(snapshot_count=2)
    cover = bundle.content.cover_asset_ids[0]
    bundle.content.cover_asset_metadata = [
        {
            "id": cover,
            "object_key": "workspaces/private/cover.png",
            "file_name": "private-cover.png",
            "mime_type": "image/png",
            "size": 2048,
        }
    ]
    provider = RecordingProvider(MockAnalysisAdapter().analyze(bundle))

    report = QianwenAnalysisAdapter(
        cast("object", provider),
        platform="douyin",
    ).analyze(bundle)
    report.validate_references(bundle)

    sent = provider.requests[0]
    assert sent.response_model is AnalysisReport
    assert sent.inputs["platform"] == "douyin"
    assert sent.inputs["cover"] == {
        "present": True,
        "count": 1,
        "visual_analysis_performed": False,
    }
    assert sent.inputs["allowed_evidence_ids"] == sorted(bundle.evidence_ids())
    serialized = str(sent.inputs)
    for forbidden in (
        "workspaces/private/cover.png",
        "private-cover.png",
        "https://",
        "download_url",
        "provider_workspace_id",
        "api_key",
    ):
        assert forbidden not in serialized


def test_analysis_adapter_does_not_hide_unknown_evidence_reference() -> None:
    from app.modules.models.adapters.qianwen_analysis import (
        QianwenAnalysisAdapter,
    )

    bundle = evidence_bundle()
    invalid = MockAnalysisAdapter().analyze(bundle)
    invalid.recommendations[0].evidence_ids = ["outside:bundle"]
    provider = RecordingProvider(invalid)

    report = QianwenAnalysisAdapter(
        cast("object", provider),
        platform="douyin",
    ).analyze(bundle)

    with pytest.raises(ValueError, match="unknown evidence"):
        report.validate_references(bundle)


def test_analysis_sync_bridge_rejects_an_existing_event_loop() -> None:
    import asyncio

    from app.modules.models.adapters.qianwen_analysis import (
        QianwenAnalysisAdapter,
    )

    bundle = evidence_bundle()
    provider = RecordingProvider(MockAnalysisAdapter().analyze(bundle))
    adapter = QianwenAnalysisAdapter(
        cast("object", provider),
        platform="douyin",
    )

    async def call_inside_loop() -> None:
        with pytest.raises(RuntimeError, match="event loop"):
            adapter.analyze(bundle)

    asyncio.run(call_inside_loop())
