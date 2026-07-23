from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.modules.content.account_models import Platform
from app.modules.risk_rag.evaluation import (
    build_ci_evaluation_payload,
    ControlledEvaluationRequired,
    EvaluationMetricStatus,
    EvaluationPrediction,
    EvaluationRunVersions,
    EvaluationThresholds,
    Severity,
    evaluate_platform,
    load_platform_evaluation_set,
    run_fixed_mock_regression,
    run_real_model_evaluation,
)


FIXTURES = Path(__file__).parents[1] / "fixtures" / "risk_eval"
SCENARIOS = {
    "explicit_violation",
    "safe",
    "boundary",
    "contact_variant",
    "image_text_variant",
    "ocr_low_confidence",
    "no_active_evidence",
    "citation_valid",
    "citation_invalid",
    "s5_only_high_risk",
    "historical_rule",
}
VERSIONS = EvaluationRunVersions(
    rule_version="risk-rules-v1",
    prompt_version="risk-prompt-v1",
    model_version="fixed-contract-mock-v1",
    embedding_version="mock-embedding-v1",
)
RUN_AT = datetime(2026, 7, 23, 10, tzinfo=UTC)


def test_platform_fixtures_are_separate_synthetic_and_fully_labelled() -> None:
    douyin = load_platform_evaluation_set(FIXTURES, Platform.DOUYIN)
    xiaohongshu = load_platform_evaluation_set(
        FIXTURES,
        Platform.XIAOHONGSHU,
    )

    assert len(douyin.cases) == len(xiaohongshu.cases) == 11
    for dataset in (douyin, xiaohongshu):
        assert {case.scenario for case in dataset.cases} == SCENARIOS
        assert all(case.platform is dataset.platform for case in dataset.cases)
        assert all(case.source == "artificially_generated" for case in dataset.cases)
        assert all(
            case.authorization_status == "authorized_for_test"
            for case in dataset.cases
        )


def test_platform_loader_rejects_cross_platform_fixture(tmp_path: Path) -> None:
    platform_dir = tmp_path / "douyin"
    platform_dir.mkdir()
    (platform_dir / "cases.json").write_text(
        """
        {
          "dataset_id": "polluted",
          "fixture_version": "v1",
          "platform": "douyin",
          "cases": [{
            "fixture_id": "wrong-platform",
            "scenario": "safe",
            "source": "artificially_generated",
            "authorization_status": "authorized_for_test",
            "platform": "xiaohongshu",
            "input": {"title": "SYN", "body": "", "cover_ocr_text": "", "ocr_confidence": null},
            "expected": {"high_risk": false, "severity": "none", "citation_validation": "not_required", "requires_human_review": false, "evidence_status": "active"}
          }]
        }
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="cross-platform"):
        load_platform_evaluation_set(tmp_path, Platform.DOUYIN)


def test_platform_loader_rejects_unapproved_provenance(tmp_path: Path) -> None:
    platform_dir = tmp_path / "douyin"
    platform_dir.mkdir()
    (platform_dir / "cases.json").write_text(
        """
        {
          "dataset_id": "unsafe",
          "fixture_version": "v1",
          "platform": "douyin",
          "cases": [{
            "fixture_id": "unsafe",
            "scenario": "safe",
            "source": "private_export",
            "authorization_status": "unknown",
            "platform": "douyin",
            "input": {"title": "SYN", "body": "", "cover_ocr_text": "", "ocr_confidence": null},
            "expected": {"high_risk": false, "severity": "none", "citation_validation": "not_required", "requires_human_review": false, "evidence_status": "active"}
          }]
        }
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="synthetic or explicitly authorized"):
        load_platform_evaluation_set(tmp_path, Platform.DOUYIN)


def _perfect_predictions(dataset):
    return tuple(
        EvaluationPrediction(
            fixture_id=case.fixture_id,
            high_risk=case.expected_high_risk,
            severity=case.expected_severity,
            citation_count=(
                1 if case.citation_validation == "valid" else 0
            ),
            valid_citation_count=(
                1 if case.citation_validation == "valid" else 0
            ),
            conclusion_count=(
                0 if case.citation_validation == "reject" else 1
            ),
            supported_conclusion_count=(
                0 if case.citation_validation == "reject" else 1
            ),
            requires_human_review=case.requires_human_review,
        )
        for case in dataset.cases
    )


def test_metrics_have_explicit_denominators_and_empty_rules_per_platform() -> None:
    dataset = load_platform_evaluation_set(FIXTURES, Platform.DOUYIN)
    predictions = _perfect_predictions(dataset)

    report = evaluate_platform(
        dataset,
        (predictions, predictions),
        versions=VERSIONS,
        run_at=RUN_AT,
    )

    assert report.platform is Platform.DOUYIN
    assert report.sample_count == 11
    assert report.fixture_version == "2026-07-23.1"
    assert report.versions == VERSIONS
    assert report.run_at == RUN_AT
    assert report.high_risk_recall.value == 1.0
    assert report.high_risk_recall.denominator == 4
    assert report.safe_false_positive_rate.value == 0.0
    assert report.safe_false_positive_rate.denominator == 1
    assert report.citation_correctness.value == 1.0
    assert report.unsupported_conclusion_rate.value == 0.0
    assert report.severity_accuracy.value == 1.0
    assert report.severity_accuracy.denominator == 11
    assert report.ocr_low_confidence_downgrade_accuracy.value == 1.0
    assert report.ocr_low_confidence_downgrade_accuracy.denominator == 1
    assert report.consistency.value == 1.0
    assert report.production_quality_claim_allowed is False
    assert report.quality_label == "ENGINEERING_REGRESSION_ONLY"


def test_bad_predictions_fail_all_quality_dimensions() -> None:
    dataset = load_platform_evaluation_set(FIXTURES, Platform.DOUYIN)
    predictions = tuple(
        EvaluationPrediction(
            fixture_id=case.fixture_id,
            high_risk=not case.expected_high_risk,
            severity=Severity.NONE
            if case.expected_severity is not Severity.NONE
            else Severity.HIGH,
            citation_count=1,
            valid_citation_count=0,
            conclusion_count=1,
            supported_conclusion_count=0,
            requires_human_review=not case.requires_human_review,
        )
        for case in dataset.cases
    )

    report = evaluate_platform(
        dataset,
        (
            predictions,
            (
                replace(
                    predictions[0],
                    high_risk=not predictions[0].high_risk,
                ),
                *predictions[1:],
            ),
        ),
        versions=VERSIONS,
        run_at=RUN_AT,
    )

    assert report.high_risk_recall.value == 0.0
    assert report.safe_false_positive_rate.value == 1.0
    assert report.citation_correctness.value == 0.0
    assert report.unsupported_conclusion_rate.value == 1.0
    assert report.severity_accuracy.value == 0.0
    assert report.ocr_low_confidence_downgrade_accuracy.value == 0.0
    assert report.consistency.value == 0.0


def test_insufficient_samples_block_gate_and_never_become_quality_claim() -> None:
    dataset = load_platform_evaluation_set(FIXTURES, Platform.DOUYIN)
    report = evaluate_platform(
        dataset,
        (_perfect_predictions(dataset),),
        versions=VERSIONS,
        run_at=RUN_AT,
        thresholds=EvaluationThresholds(
            minimum_metric_denominator=12,
        ),
    )

    assert all(
        metric.status is EvaluationMetricStatus.INSUFFICIENT_SAMPLE
        for metric in report.quality_metrics
    )
    assert report.gate.passed is False
    assert report.gate.code == "INSUFFICIENT_SAMPLE"
    assert report.production_quality_claim_allowed is False


def test_fixed_mock_reports_each_platform_without_aggregate_metric() -> None:
    result = run_fixed_mock_regression(
        FIXTURES,
        versions=VERSIONS,
        run_at=RUN_AT,
        repetitions=3,
    )

    assert {report.platform for report in result.platform_reports} == {
        Platform.DOUYIN,
        Platform.XIAOHONGSHU,
    }
    assert all(report.gate.passed for report in result.platform_reports)
    assert result.provider == "fixed-contract-mock"
    assert result.used_network is False
    assert not hasattr(result, "aggregate_report")


def test_ci_payload_is_fixed_mock_per_platform_and_not_marketing_copy() -> None:
    payload = build_ci_evaluation_payload(
        FIXTURES,
        versions=VERSIONS,
        run_at=RUN_AT,
    )

    assert payload["provider"] == "fixed-contract-mock"
    assert payload["used_network"] is False
    assert payload["quality_label"] == "ENGINEERING_REGRESSION_ONLY"
    assert payload["production_quality_claim_allowed"] is False
    assert set(payload["platforms"]) == {"douyin", "xiaohongshu"}
    assert all(
        platform["gate"]["passed"]
        for platform in payload["platforms"].values()
    )


def test_real_model_evaluation_requires_explicit_controlled_release() -> None:
    called = False

    def provider(_case):
        nonlocal called
        called = True
        raise AssertionError("provider must not run without release control")

    with pytest.raises(ControlledEvaluationRequired):
        run_real_model_evaluation(
            (
                load_platform_evaluation_set(
                    FIXTURES,
                    Platform.DOUYIN,
                ),
            ),
            provider=provider,
            controlled_release=False,
            versions=VERSIONS,
            run_at=RUN_AT,
        )

    assert called is False
