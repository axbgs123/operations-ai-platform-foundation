from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.analysis.features import (
    BenchmarkEvidenceInput,
    ComparableContentEvidenceInput,
    ContentEvidenceInput,
    CoverAssetEvidenceInput,
    MetricEvidenceInput,
    SnapshotEvidenceInput,
    build_analysis_evidence,
)
from app.modules.analysis.schemas import AnalysisReport, MockAnalysisAdapter
from app.modules.analysis.schemas import HttpAnalysisAdapter, get_analysis_adapter
from app.core.config import Settings
import app.modules.analysis.schemas as analysis_schemas


def evidence_bundle(*, snapshot_count: int = 1, sample_count: int = 12):
    content_id = uuid4()
    benchmark_id = uuid4()
    start = datetime(2026, 7, 20, 8, tzinfo=UTC)
    snapshots = [
        SnapshotEvidenceInput(
            id=uuid4(),
            collected_at=start + timedelta(hours=index + 1),
            maturity_bucket="24h",
            metrics=[
                MetricEvidenceInput(key="views", value=str(1000 + index * 200)),
                MetricEvidenceInput(key="likes", value=str(100 + index * 20)),
            ],
        )
        for index in range(snapshot_count)
    ]
    return build_analysis_evidence(
        ContentEvidenceInput(
            id=content_id,
            title="三步讲清 AI 工作流",
            body="先说明痛点，再拆解方法，最后给出行动建议。",
            cover_asset_ids=[uuid4()],
        ),
        snapshots,
        BenchmarkEvidenceInput(
            id=benchmark_id,
            sample_count=sample_count,
            confidence=(
                "normal"
                if sample_count >= 10
                else "low_confidence"
                if sample_count >= 5
                else "raw_only"
            ),
            percentiles={
                "views": {"median": "700", "p75": "900", "p90": "1100"},
                "likes": {"median": "70", "p75": "90", "p90": "120"},
            },
        ),
    )


def test_report_schema_requires_every_analysis_section() -> None:
    report = MockAnalysisAdapter().analyze(evidence_bundle())
    payload = report.model_dump()

    required = {
        "data_performance",
        "title_issues",
        "copy_issues",
        "cover_issues",
        "evidence",
        "causal_hypotheses",
        "confidence",
        "recommendations",
        "next_experiments",
    }
    assert required <= payload.keys()
    for field in required:
        incomplete = dict(payload)
        incomplete.pop(field)
        with pytest.raises(ValidationError):
            AnalysisReport.model_validate(incomplete)


def test_evidence_bundle_is_deterministic_and_model_references_only_bundle_ids() -> None:
    bundle = evidence_bundle(snapshot_count=2)
    rebuilt = build_analysis_evidence(
        bundle.content,
        bundle.snapshots,
        bundle.benchmark,
    )
    report = MockAnalysisAdapter().analyze(bundle)

    assert rebuilt.model_dump(mode="json") == bundle.model_dump(mode="json")
    assert bundle.trend_allowed is True
    assert bundle.confidence_ceiling == "high"
    assert report.referenced_evidence_ids() <= bundle.evidence_ids()


def test_one_snapshot_has_no_trend_and_small_benchmark_degrades_confidence() -> None:
    one_snapshot = evidence_bundle(snapshot_count=1, sample_count=4)
    report = MockAnalysisAdapter().analyze(one_snapshot)

    assert one_snapshot.trend_allowed is False
    assert one_snapshot.confidence_ceiling == "low"
    assert report.data_performance.trend_conclusion is None
    assert report.confidence == "low"
    assert report.degradation_notice


def test_report_rejects_a_reference_missing_from_the_evidence_bundle() -> None:
    bundle = evidence_bundle()
    report = MockAnalysisAdapter().analyze(bundle)
    report.recommendations[0].evidence_ids = ["evidence:not-in-bundle"]

    with pytest.raises(ValueError, match="unknown evidence"):
        report.validate_references(bundle)


def test_report_cannot_exceed_confidence_ceiling_or_hide_degradation() -> None:
    bundle = evidence_bundle(sample_count=4)
    report = MockAnalysisAdapter().analyze(bundle)
    report.confidence = "high"
    report.recommendations[0].confidence = "high"
    report.degradation_notice = None

    with pytest.raises(ValueError, match="confidence ceiling|degradation"):
        report.validate_references(bundle)


def test_bundle_contains_real_cover_metadata_and_high_low_comparisons() -> None:
    bundle = evidence_bundle(snapshot_count=2)
    cover_id = bundle.content.cover_asset_ids[0]
    content = bundle.content.model_copy(
        update={
            "cover_asset_metadata": [
                CoverAssetEvidenceInput(
                    id=cover_id,
                    object_key="workspaces/synthetic/cover.png",
                    file_name="synthetic-cover.png",
                    mime_type="image/png",
                    size=2048,
                )
            ]
        }
    )
    comparisons = [
        ComparableContentEvidenceInput(
            content_id=uuid4(),
            snapshot_id=uuid4(),
            title="相似高表现合成样本",
            performance_band="high",
            metric_key="views",
            metric_value="1600",
            similarity_basis="同账号、平台、内容类型与数据成熟度",
        ),
        ComparableContentEvidenceInput(
            content_id=uuid4(),
            snapshot_id=uuid4(),
            title="相似低表现合成样本",
            performance_band="low",
            metric_key="views",
            metric_value="400",
            similarity_basis="同账号、平台、内容类型与数据成熟度",
        ),
    ]

    enriched = build_analysis_evidence(
        content,
        bundle.snapshots,
        bundle.benchmark,
        comparisons,
    )

    cover = next(item for item in enriched.items if item.kind == "cover")
    comparison_items = [item for item in enriched.items if item.kind == "comparison"]
    assert "synthetic-cover.png" in cover.value
    assert "image/png" in cover.value
    assert len(comparison_items) == 2
    assert {item.label for item in comparison_items} == {
        "相似高表现内容",
        "相似低表现内容",
    }


def test_missing_one_expected_metric_caps_confidence_at_low() -> None:
    complete = evidence_bundle(snapshot_count=2)
    incomplete_snapshots = [
        snapshot.model_copy(
            update={
                "metrics": [
                    metric for metric in snapshot.metrics if metric.key == "views"
                ]
            }
        )
        for snapshot in complete.snapshots
    ]

    incomplete = build_analysis_evidence(
        complete.content,
        incomplete_snapshots,
        complete.benchmark,
    )

    assert incomplete.confidence_ceiling == "low"


def test_non_mock_mode_requires_and_selects_configured_http_adapter(monkeypatch) -> None:
    missing = Settings(app_mock_mode=False, analysis_adapter_url=None)
    monkeypatch.setattr(analysis_schemas, "get_settings", lambda: missing)
    with pytest.raises(RuntimeError, match="adapter URL"):
        get_analysis_adapter()

    configured = Settings(
        app_mock_mode=False,
        analysis_adapter_url="https://model-gateway.test/analyze",
        analysis_model_version="synthetic-provider-v2",
    )
    monkeypatch.setattr(analysis_schemas, "get_settings", lambda: configured)
    adapter = get_analysis_adapter()
    assert isinstance(adapter, HttpAnalysisAdapter)
    assert adapter.model_version == "synthetic-provider-v2"
