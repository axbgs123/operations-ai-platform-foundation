from __future__ import annotations

import json
import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from app.modules.content.account_models import Platform


EvaluationScenario = Literal[
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
]
CitationValidation = Literal["valid", "reject", "not_required"]
ALLOWED_SOURCES = {"artificially_generated", "explicitly_authorized"}
ALLOWED_AUTHORIZATION = {"authorized_for_test", "authorized"}


class Severity(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EvaluationMetricStatus(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"


@dataclass(frozen=True)
class EvaluationCase:
    fixture_id: str
    platform: Platform
    scenario: EvaluationScenario
    source: str
    authorization_status: str
    title: str
    body: str
    cover_ocr_text: str
    ocr_confidence: float | None
    expected_high_risk: bool
    expected_severity: Severity
    citation_validation: CitationValidation
    requires_human_review: bool
    evidence_status: str


@dataclass(frozen=True)
class PlatformEvaluationSet:
    dataset_id: str
    fixture_version: str
    platform: Platform
    cases: tuple[EvaluationCase, ...]


@dataclass(frozen=True)
class EvaluationPrediction:
    fixture_id: str
    high_risk: bool
    severity: Severity
    citation_count: int
    valid_citation_count: int
    conclusion_count: int
    supported_conclusion_count: int
    requires_human_review: bool

    def __post_init__(self) -> None:
        if not 0 <= self.valid_citation_count <= self.citation_count:
            raise ValueError("valid citation count must be within citation count")
        if not 0 <= self.supported_conclusion_count <= self.conclusion_count:
            raise ValueError(
                "supported conclusion count must be within conclusion count"
            )


@dataclass(frozen=True)
class EvaluationRunVersions:
    rule_version: str
    prompt_version: str
    model_version: str
    embedding_version: str


@dataclass(frozen=True)
class EvaluationThresholds:
    minimum_high_risk_recall: float = 0.90
    maximum_safe_false_positive_rate: float = 0.10
    minimum_citation_correctness: float = 0.95
    maximum_unsupported_conclusion_rate: float = 0.01
    minimum_severity_accuracy: float = 0.90
    minimum_ocr_low_confidence_downgrade_accuracy: float = 0.90
    minimum_consistency: float = 1.0
    minimum_metric_denominator: int = 1


@dataclass(frozen=True)
class EvaluationMetric:
    name: str
    numerator: int
    denominator: int
    value: float | None
    empty_rule: str
    status: EvaluationMetricStatus


@dataclass(frozen=True)
class EvaluationGateFailure:
    metric: str
    actual: float | None
    threshold: float
    reason: str


@dataclass(frozen=True)
class EvaluationGate:
    passed: bool
    code: str
    failures: tuple[EvaluationGateFailure, ...]


@dataclass(frozen=True)
class PlatformEvaluationReport:
    platform: Platform
    fixture_version: str
    sample_count: int
    versions: EvaluationRunVersions
    run_at: datetime
    high_risk_recall: EvaluationMetric
    safe_false_positive_rate: EvaluationMetric
    citation_correctness: EvaluationMetric
    unsupported_conclusion_rate: EvaluationMetric
    severity_accuracy: EvaluationMetric
    ocr_low_confidence_downgrade_accuracy: EvaluationMetric
    consistency: EvaluationMetric
    gate: EvaluationGate
    quality_label: str = "ENGINEERING_REGRESSION_ONLY"
    production_quality_claim_allowed: bool = False

    @property
    def quality_metrics(self) -> tuple[EvaluationMetric, ...]:
        return (
            self.high_risk_recall,
            self.safe_false_positive_rate,
            self.citation_correctness,
            self.unsupported_conclusion_rate,
            self.severity_accuracy,
            self.ocr_low_confidence_downgrade_accuracy,
            self.consistency,
        )


@dataclass(frozen=True)
class FixedMockRegressionResult:
    platform_reports: tuple[PlatformEvaluationReport, ...]
    provider: str = "fixed-contract-mock"
    used_network: bool = False


class ControlledEvaluationRequired(RuntimeError):
    pass


def load_platform_evaluation_set(
    root: Path,
    platform: Platform,
) -> PlatformEvaluationSet:
    path = root / platform.value / "cases.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw["platform"] != platform.value:
        raise ValueError("cross-platform evaluation dataset rejected")
    cases: list[EvaluationCase] = []
    seen_ids: set[str] = set()
    for item in raw["cases"]:
        if item["platform"] != platform.value:
            raise ValueError("cross-platform evaluation fixture rejected")
        if (
            item["source"] not in ALLOWED_SOURCES
            or item["authorization_status"] not in ALLOWED_AUTHORIZATION
        ):
            raise ValueError(
                "fixtures must be synthetic or explicitly authorized"
            )
        if item["fixture_id"] in seen_ids:
            raise ValueError("fixture ids must be unique within a platform")
        seen_ids.add(item["fixture_id"])
        fixture_input = item["input"]
        expected = item["expected"]
        cases.append(
            EvaluationCase(
                fixture_id=item["fixture_id"],
                platform=platform,
                scenario=item["scenario"],
                source=item["source"],
                authorization_status=item["authorization_status"],
                title=fixture_input["title"],
                body=fixture_input["body"],
                cover_ocr_text=fixture_input["cover_ocr_text"],
                ocr_confidence=fixture_input["ocr_confidence"],
                expected_high_risk=expected["high_risk"],
                expected_severity=Severity(expected["severity"]),
                citation_validation=expected["citation_validation"],
                requires_human_review=expected["requires_human_review"],
                evidence_status=expected["evidence_status"],
            )
        )
    return PlatformEvaluationSet(
        dataset_id=raw["dataset_id"],
        fixture_version=raw["fixture_version"],
        platform=platform,
        cases=tuple(cases),
    )


def _metric(
    name: str,
    numerator: int,
    denominator: int,
    *,
    minimum_denominator: int,
    empty_rule: str,
) -> EvaluationMetric:
    sufficient = denominator >= minimum_denominator and denominator > 0
    return EvaluationMetric(
        name=name,
        numerator=numerator,
        denominator=denominator,
        value=numerator / denominator if denominator else None,
        empty_rule=empty_rule,
        status=(
            EvaluationMetricStatus.SUFFICIENT
            if sufficient
            else EvaluationMetricStatus.INSUFFICIENT_SAMPLE
        ),
    )


def _gate(
    metrics: Sequence[EvaluationMetric],
    thresholds: EvaluationThresholds,
) -> EvaluationGate:
    if any(
        metric.status is EvaluationMetricStatus.INSUFFICIENT_SAMPLE
        for metric in metrics
    ):
        insufficient_failures = tuple(
            EvaluationGateFailure(
                metric=metric.name,
                actual=metric.value,
                threshold=float(thresholds.minimum_metric_denominator),
                reason="INSUFFICIENT_SAMPLE",
            )
            for metric in metrics
            if metric.status is EvaluationMetricStatus.INSUFFICIENT_SAMPLE
        )
        return EvaluationGate(
            False,
            "INSUFFICIENT_SAMPLE",
            insufficient_failures,
        )

    metric_by_name = {metric.name: metric for metric in metrics}
    minimums = {
        "high_risk_recall": thresholds.minimum_high_risk_recall,
        "citation_correctness": thresholds.minimum_citation_correctness,
        "severity_accuracy": thresholds.minimum_severity_accuracy,
        "ocr_low_confidence_downgrade_accuracy": (
            thresholds.minimum_ocr_low_confidence_downgrade_accuracy
        ),
        "consistency": thresholds.minimum_consistency,
    }
    maximums = {
        "safe_false_positive_rate": (
            thresholds.maximum_safe_false_positive_rate
        ),
        "unsupported_conclusion_rate": (
            thresholds.maximum_unsupported_conclusion_rate
        ),
    }
    threshold_failures: list[EvaluationGateFailure] = []
    for name, threshold in minimums.items():
        actual = metric_by_name[name].value
        if actual is None or actual < threshold:
            threshold_failures.append(
                EvaluationGateFailure(
                    name,
                    actual,
                    threshold,
                    "BELOW_MINIMUM",
                )
            )
    for name, threshold in maximums.items():
        actual = metric_by_name[name].value
        if actual is None or actual > threshold:
            threshold_failures.append(
                EvaluationGateFailure(
                    name,
                    actual,
                    threshold,
                    "ABOVE_MAXIMUM",
                )
            )
    return EvaluationGate(
        passed=not threshold_failures,
        code="PASSED" if not threshold_failures else "REGRESSION_FAILED",
        failures=tuple(threshold_failures),
    )


def evaluate_platform(
    dataset: PlatformEvaluationSet,
    runs: Sequence[Sequence[EvaluationPrediction]],
    *,
    versions: EvaluationRunVersions,
    run_at: datetime,
    thresholds: EvaluationThresholds | None = None,
) -> PlatformEvaluationReport:
    if not runs:
        raise ValueError("at least one prediction run is required")
    expected_ids = {case.fixture_id for case in dataset.cases}
    normalized_runs: list[dict[str, EvaluationPrediction]] = []
    for run in runs:
        predictions = {prediction.fixture_id: prediction for prediction in run}
        if set(predictions) != expected_ids or len(predictions) != len(run):
            raise ValueError("each run must predict every fixture exactly once")
        normalized_runs.append(predictions)
    first = normalized_runs[0]
    limit = (thresholds or EvaluationThresholds()).minimum_metric_denominator

    high_risk_cases = [
        case for case in dataset.cases if case.expected_high_risk
    ]
    safe_cases = [
        case for case in dataset.cases if case.scenario == "safe"
    ]
    recalled = sum(first[case.fixture_id].high_risk for case in high_risk_cases)
    safe_predictions = sum(
        first[case.fixture_id].high_risk for case in safe_cases
    )
    citation_count = sum(
        prediction.citation_count for prediction in first.values()
    )
    valid_citations = sum(
        prediction.valid_citation_count for prediction in first.values()
    )
    conclusion_count = sum(
        prediction.conclusion_count for prediction in first.values()
    )
    supported_conclusions = sum(
        prediction.supported_conclusion_count
        for prediction in first.values()
    )
    correct_severity = sum(
        first[case.fixture_id].severity is case.expected_severity
        for case in dataset.cases
    )
    low_ocr_cases = [
        case
        for case in dataset.cases
        if case.scenario == "ocr_low_confidence"
    ]
    correct_low_ocr = sum(
        first[case.fixture_id].requires_human_review
        == case.requires_human_review
        for case in low_ocr_cases
    )
    baseline = tuple(first[case.fixture_id] for case in dataset.cases)
    consistent_runs = sum(
        tuple(run[case.fixture_id] for case in dataset.cases) == baseline
        for run in normalized_runs[1:]
    )
    metrics = (
        _metric(
            "high_risk_recall",
            recalled,
            len(high_risk_cases),
            minimum_denominator=limit,
            empty_rule="no expected high-risk fixtures yields no score",
        ),
        _metric(
            "safe_false_positive_rate",
            safe_predictions,
            len(safe_cases),
            minimum_denominator=limit,
            empty_rule="no safe fixtures yields no score",
        ),
        _metric(
            "citation_correctness",
            valid_citations,
            citation_count,
            minimum_denominator=limit,
            empty_rule="no emitted citations yields no score",
        ),
        _metric(
            "unsupported_conclusion_rate",
            conclusion_count - supported_conclusions,
            conclusion_count,
            minimum_denominator=limit,
            empty_rule="no conclusions yields no score",
        ),
        _metric(
            "severity_accuracy",
            correct_severity,
            len(dataset.cases),
            minimum_denominator=limit,
            empty_rule="no fixtures yields no score",
        ),
        _metric(
            "ocr_low_confidence_downgrade_accuracy",
            correct_low_ocr,
            len(low_ocr_cases),
            minimum_denominator=limit,
            empty_rule="no low-confidence OCR fixtures yields no score",
        ),
        _metric(
            "consistency",
            consistent_runs,
            len(normalized_runs) - 1,
            minimum_denominator=limit,
            empty_rule="fewer than two runs yields no score",
        ),
    )
    gate = _gate(metrics, thresholds or EvaluationThresholds())
    return PlatformEvaluationReport(
        platform=dataset.platform,
        fixture_version=dataset.fixture_version,
        sample_count=len(dataset.cases),
        versions=versions,
        run_at=run_at,
        high_risk_recall=metrics[0],
        safe_false_positive_rate=metrics[1],
        citation_correctness=metrics[2],
        unsupported_conclusion_rate=metrics[3],
        severity_accuracy=metrics[4],
        ocr_low_confidence_downgrade_accuracy=metrics[5],
        consistency=metrics[6],
        gate=gate,
    )


def _fixed_prediction(case: EvaluationCase) -> EvaluationPrediction:
    citation_count = int(case.citation_validation == "valid")
    conclusion_count = int(case.citation_validation != "reject")
    return EvaluationPrediction(
        fixture_id=case.fixture_id,
        high_risk=case.expected_high_risk,
        severity=case.expected_severity,
        citation_count=citation_count,
        valid_citation_count=citation_count,
        conclusion_count=conclusion_count,
        supported_conclusion_count=conclusion_count,
        requires_human_review=case.requires_human_review,
    )


def run_fixed_mock_regression(
    fixture_root: Path,
    *,
    versions: EvaluationRunVersions,
    run_at: datetime,
    repetitions: int = 2,
    thresholds: EvaluationThresholds | None = None,
) -> FixedMockRegressionResult:
    if repetitions < 2:
        raise ValueError("fixed mock regression requires at least two repetitions")
    reports: list[PlatformEvaluationReport] = []
    for platform in Platform:
        dataset = load_platform_evaluation_set(fixture_root, platform)
        runs = tuple(
            tuple(_fixed_prediction(case) for case in dataset.cases)
            for _ in range(repetitions)
        )
        reports.append(
            evaluate_platform(
                dataset,
                runs,
                versions=versions,
                run_at=run_at,
                thresholds=thresholds,
            )
        )
    return FixedMockRegressionResult(tuple(reports))


def _metric_payload(metric: EvaluationMetric) -> dict[str, object]:
    return {
        "numerator": metric.numerator,
        "denominator": metric.denominator,
        "value": metric.value,
        "status": metric.status.value,
        "empty_rule": metric.empty_rule,
    }


def build_ci_evaluation_payload(
    fixture_root: Path,
    *,
    versions: EvaluationRunVersions,
    run_at: datetime,
) -> dict[str, object]:
    result = run_fixed_mock_regression(
        fixture_root,
        versions=versions,
        run_at=run_at,
        repetitions=3,
    )
    platforms: dict[str, object] = {}
    for report in result.platform_reports:
        platforms[report.platform.value] = {
            "fixture_version": report.fixture_version,
            "sample_count": report.sample_count,
            "run_at": report.run_at.isoformat(),
            "versions": {
                "rule": report.versions.rule_version,
                "prompt": report.versions.prompt_version,
                "model": report.versions.model_version,
                "embedding": report.versions.embedding_version,
            },
            "metrics": {
                metric.name: _metric_payload(metric)
                for metric in report.quality_metrics
            },
            "gate": {
                "passed": report.gate.passed,
                "code": report.gate.code,
                "failures": [
                    {
                        "metric": failure.metric,
                        "actual": failure.actual,
                        "threshold": failure.threshold,
                        "reason": failure.reason,
                    }
                    for failure in report.gate.failures
                ],
            },
        }
    return {
        "provider": result.provider,
        "used_network": result.used_network,
        "quality_label": "ENGINEERING_REGRESSION_ONLY",
        "production_quality_claim_allowed": False,
        "platforms": platforms,
    }


def run_real_model_evaluation(
    datasets: Sequence[PlatformEvaluationSet],
    *,
    provider: Callable[[EvaluationCase], EvaluationPrediction],
    controlled_release: bool,
    versions: EvaluationRunVersions,
    run_at: datetime,
    thresholds: EvaluationThresholds | None = None,
) -> tuple[PlatformEvaluationReport, ...]:
    if not controlled_release:
        raise ControlledEvaluationRequired(
            "real model evaluation is a controlled pre-release task"
        )
    return tuple(
        evaluate_platform(
            dataset,
            (tuple(provider(case) for case in dataset.cases),),
            versions=versions,
            run_at=run_at,
            thresholds=thresholds,
        )
        for dataset in datasets
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run fixed synthetic RiskRAG regression gates."
    )
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--rule-version", default="ci-risk-rules")
    parser.add_argument("--prompt-version", default="ci-risk-prompt")
    parser.add_argument("--model-version", default="fixed-contract-mock-v1")
    parser.add_argument("--embedding-version", default="mock-embedding-v1")
    arguments = parser.parse_args()
    payload = build_ci_evaluation_payload(
        arguments.fixtures,
        versions=EvaluationRunVersions(
            rule_version=arguments.rule_version,
            prompt_version=arguments.prompt_version,
            model_version=arguments.model_version,
            embedding_version=arguments.embedding_version,
        ),
        run_at=datetime.now(UTC),
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    platform_payloads = payload["platforms"]
    assert isinstance(platform_payloads, dict)
    return int(
        not all(
            isinstance(item, dict)
            and isinstance(item.get("gate"), dict)
            and item["gate"].get("passed") is True
            for item in platform_payloads.values()
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
