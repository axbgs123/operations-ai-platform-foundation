from collections.abc import Sequence

from app.modules.generation.publication_gate import (
    NO_ACTIVE_RISK_EVIDENCE,
    DraftForPublication,
    GateStep,
    RiskFinding,
    RiskScanInput,
    RiskScanResult,
    RiskSeverity,
    evaluate_publication_gate,
)
from app.modules.style_facts.fact_verification import GeneratedClaim


class RecordingRiskScanner:
    def __init__(self, result: RiskScanResult) -> None:
        self.result = result
        self.inputs: list[RiskScanInput] = []

    def scan(self, data: RiskScanInput) -> RiskScanResult:
        self.inputs.append(data)
        return self.result


def draft(
    *,
    claims: Sequence[GeneratedClaim] = (),
) -> DraftForPublication:
    return DraftForPublication(
        title="夏日亚麻衬衫",
        copy="已确认面料：亚麻。",
        cover_text=("夏日亚麻", "轻盈穿搭"),
        claims=tuple(claims),
        platform="xiaohongshu",
        risk_rule_version="risk-v1",
    )


def safe_scan() -> RiskScanResult:
    return RiskScanResult(
        findings=(),
        evidence_available=True,
        rule_version="risk-v1",
    )


def test_gate_records_the_required_order_before_allowing_draft_save() -> None:
    scanner = RecordingRiskScanner(safe_scan())
    material_claim = GeneratedClaim(field_name="material", value="亚麻")

    decision = evaluate_publication_gate(
        draft(claims=(material_claim,)),
        confirmed_facts={material_claim.field_code: "亚麻"},
        risk_scanner=scanner,
    )

    assert decision.steps == (
        GateStep.STRUCTURE_VALIDATION,
        GateStep.FACT_RECHECK,
        GateStep.RISK_SCAN,
        GateStep.SAVE_DRAFT,
    )
    assert decision.can_save_draft is True
    assert decision.can_enter_pending_publication is True
    assert scanner.inputs == [
        RiskScanInput(
            title="夏日亚麻衬衫",
            copy="已确认面料：亚麻。",
            cover_text=("夏日亚麻", "轻盈穿搭"),
            platform="xiaohongshu",
            rule_version="risk-v1",
        )
    ]


def test_invalid_structure_stops_before_fact_or_risk_checks() -> None:
    scanner = RecordingRiskScanner(safe_scan())

    decision = evaluate_publication_gate(
        draft().model_copy(update={"title": " "}),
        confirmed_facts={},
        risk_scanner=scanner,
    )

    assert decision.steps == (GateStep.STRUCTURE_VALIDATION,)
    assert decision.can_save_draft is False
    assert decision.can_enter_pending_publication is False
    assert decision.error_code == "INVALID_GENERATION_STRUCTURE"
    assert scanner.inputs == []


def test_high_risk_fact_conflict_blocks_pending_but_preserves_draft() -> None:
    scanner = RecordingRiskScanner(safe_scan())

    decision = evaluate_publication_gate(
        draft(claims=(GeneratedClaim(field_name="price", value="99 元"),)),
        confirmed_facts={"price": "199 元"},
        risk_scanner=scanner,
    )

    assert decision.can_save_draft is True
    assert decision.can_enter_pending_publication is False
    assert decision.error_code == "FACT_CONFLICT"
    assert decision.fact_issues[0].high_risk is True
    assert decision.steps[-1] is GateStep.SAVE_DRAFT


def test_high_risk_rag_finding_blocks_pending_and_keeps_citation() -> None:
    scanner = RecordingRiskScanner(
        RiskScanResult(
            findings=(
                RiskFinding(
                    code="PLATFORM_PROHIBITED_CLAIM",
                    severity=RiskSeverity.HIGH,
                    message="命中平台禁止的绝对化表达",
                    citations=("risk-document:v3:chunk-7",),
                ),
            ),
            evidence_available=True,
            rule_version="risk-v1",
        )
    )

    decision = evaluate_publication_gate(
        draft(),
        confirmed_facts={},
        risk_scanner=scanner,
    )

    assert decision.can_save_draft is True
    assert decision.can_enter_pending_publication is False
    assert decision.error_code == "RISK_REVIEW_REQUIRED"
    assert decision.risk_result == scanner.result


def test_no_material_and_no_active_risk_evidence_are_explainable() -> None:
    scanner = RecordingRiskScanner(
        RiskScanResult(
            findings=(),
            evidence_available=False,
            error_code=NO_ACTIVE_RISK_EVIDENCE,
            rule_version="risk-v1",
        )
    )

    decision = evaluate_publication_gate(
        draft(),
        confirmed_facts={},
        risk_scanner=scanner,
    )

    assert decision.can_save_draft is True
    assert decision.can_enter_pending_publication is False
    assert decision.error_code == NO_ACTIVE_RISK_EVIDENCE
    assert "无事实资料约束" in decision.warnings
    assert "未检索到有效风控证据" in decision.warnings
    assert decision.risk_result is not None
    assert decision.risk_result.findings == ()


def test_low_risk_fact_issue_is_reported_without_blocking_pending() -> None:
    decision = evaluate_publication_gate(
        draft(claims=(GeneratedClaim(field_name="color", value="海盐蓝"),)),
        confirmed_facts={"color": "雾霾蓝"},
        risk_scanner=RecordingRiskScanner(safe_scan()),
    )

    assert decision.can_save_draft is True
    assert decision.can_enter_pending_publication is True
    assert decision.fact_issues[0].high_risk is False
    assert "存在低风险事实差异，请人工复核" in decision.warnings
