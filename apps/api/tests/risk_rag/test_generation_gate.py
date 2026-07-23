from datetime import UTC, datetime
from uuid import uuid4

from app.modules.content.account_models import Platform
from app.modules.generation.publication_gate import (
    DraftForPublication,
    RiskSeverity,
    evaluate_publication_gate,
)
from app.modules.risk_rag.models import RiskScanNode
from app.modules.risk_rag.scanner import (
    GenerationRiskScannerAdapter,
    OcrResult,
    OcrStatus,
    RiskFinding,
    RiskFindingOrigin,
    RiskRegion,
    RiskScanInput,
    RiskScanOutput,
    RiskScanVersions,
    ScanSeverity,
)
from app.modules.style_facts.fact_verification import GeneratedClaim


def test_generation_adapter_scans_after_generation_before_draft_gate() -> None:
    captured: list[RiskScanInput] = []
    workspace_id = uuid4()
    account_id = uuid4()
    content_id = uuid4()
    versions = RiskScanVersions(
        rule_version="rules-v1",
        evidence_version="evidence-v1",
        embedding_model_id="mock-risk-embedding",
        embedding_version="embed-v1",
        embedding_dimension=3,
        rag_model_version="mock-rag-v1",
        scanner_version="scanner-v1",
    )

    def execute(scan_input: RiskScanInput) -> RiskScanOutput:
        captured.append(scan_input)
        return RiskScanOutput(
            findings=(
                RiskFinding(
                    risk_type="synthetic-high",
                    severity=ScanSeverity.HIGH,
                    matched_content="SYNTHETIC_HIGH",
                    region=RiskRegion.BODY,
                    evidence_document_ids=(uuid4(),),
                    reason="人工合成高风险规则命中",
                    suggestion="人工复核",
                    origin=RiskFindingOrigin.DETERMINISTIC,
                    deterministic_confirmed=True,
                ),
            ),
            ocr_status=OcrStatus.EMPTY,
            diagnostics=(),
            error_code=None,
            versions=versions,
            scanned_at=datetime(2026, 7, 23, 8, tzinfo=UTC),
        )

    adapter = GenerationRiskScannerAdapter(
        workspace_id=workspace_id,
        account_id=account_id,
        content_id=content_id,
        ocr=OcrResult(status=OcrStatus.EMPTY, regions=()),
        versions=versions,
        execute=execute,
        idempotency_key_factory=lambda: "generation-risk-scan-1",
        now=lambda: datetime(2026, 7, 23, 8, tzinfo=UTC),
    )
    decision = evaluate_publication_gate(
        DraftForPublication(
            title="人工生成标题",
            copy="包含 SYNTHETIC_HIGH 的人工文案",
            platform="douyin",
            risk_rule_version="rules-v1",
        ),
        confirmed_facts={},
        risk_scanner=adapter,
    )

    assert captured[0].node is RiskScanNode.AFTER_GENERATION
    assert captured[0].workspace_id == workspace_id
    assert decision.can_save_draft is True
    assert decision.can_enter_pending_publication is False
    assert decision.error_code == "RISK_REVIEW_REQUIRED"
    assert decision.risk_result is not None
    assert decision.risk_result.findings[0].severity is RiskSeverity.HIGH


def test_fact_conflict_still_blocks_when_risk_scan_is_traceable() -> None:
    versions = RiskScanVersions(
        rule_version="rules-v1",
        evidence_version="evidence-v1",
        embedding_model_id="mock-risk-embedding",
        embedding_version="embed-v1",
        embedding_dimension=3,
        rag_model_version="mock-rag-v1",
        scanner_version="scanner-v1",
    )
    adapter = GenerationRiskScannerAdapter(
        workspace_id=uuid4(),
        account_id=uuid4(),
        content_id=uuid4(),
        ocr=OcrResult(status=OcrStatus.EMPTY, regions=()),
        versions=versions,
        execute=lambda _: RiskScanOutput(
            findings=(),
            ocr_status=OcrStatus.EMPTY,
            diagnostics=(),
            error_code=None,
            versions=versions,
            scanned_at=datetime(2026, 7, 23, 8, tzinfo=UTC),
        ),
        idempotency_key_factory=lambda: "generation-risk-scan-2",
        now=lambda: datetime(2026, 7, 23, 8, tzinfo=UTC),
    )

    decision = evaluate_publication_gate(
        DraftForPublication(
            title="人工生成标题",
            copy="人工生成正文",
            platform=Platform.DOUYIN,
            risk_rule_version="rules-v1",
            claims=(
                GeneratedClaim(
                    field_name="price",
                    value="999",
                ),
            ),
        ),
        confirmed_facts={"price": "100"},
        risk_scanner=adapter,
    )

    assert decision.can_enter_pending_publication is False
    assert decision.error_code == "FACT_CONFLICT"
