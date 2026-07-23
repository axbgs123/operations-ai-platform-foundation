from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.style_facts.fact_verification import (
    FACT_CONFLICT,
    ClaimIssue,
    GeneratedClaim,
    verify_generated_claims,
)


NO_ACTIVE_RISK_EVIDENCE = "NO_ACTIVE_RISK_EVIDENCE"


class GateStep(StrEnum):
    STRUCTURE_VALIDATION = "structure_validation"
    FACT_RECHECK = "fact_recheck"
    RISK_SCAN = "risk_scan"
    SAVE_DRAFT = "save_draft"


class RiskSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ImmutableGateModel(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )


class DraftForPublication(ImmutableGateModel):
    title: str = Field(max_length=2_000)
    copy_text: str = Field(alias="copy", max_length=100_000)
    cover_text: tuple[str, ...] = Field(default=(), max_length=20)
    claims: tuple[GeneratedClaim, ...] = ()
    platform: Literal["douyin", "xiaohongshu"]
    risk_rule_version: str = Field(min_length=1, max_length=160)


class RiskScanInput(ImmutableGateModel):
    title: str
    copy_text: str = Field(alias="copy")
    cover_text: tuple[str, ...]
    platform: Literal["douyin", "xiaohongshu"]
    rule_version: str


class RiskFinding(ImmutableGateModel):
    code: str = Field(min_length=1, max_length=160)
    severity: RiskSeverity
    message: str = Field(min_length=1, max_length=2_000)
    citations: tuple[str, ...] = ()


class RiskScanResult(ImmutableGateModel):
    findings: tuple[RiskFinding, ...]
    evidence_available: bool
    rule_version: str = Field(min_length=1, max_length=160)
    error_code: str | None = None

    @model_validator(mode="after")
    def require_explicit_no_evidence_result(self) -> Self:
        if not self.evidence_available and self.error_code != NO_ACTIVE_RISK_EVIDENCE:
            raise ValueError("missing risk evidence must use NO_ACTIVE_RISK_EVIDENCE")
        return self


class RiskScanner(Protocol):
    def scan(self, data: RiskScanInput) -> RiskScanResult: ...


class NoActiveRiskEvidenceScanner:
    """Deterministic bridge until the governed RiskRAG scanner is installed."""

    def scan(self, data: RiskScanInput) -> RiskScanResult:
        return RiskScanResult(
            findings=(),
            evidence_available=False,
            rule_version=data.rule_version,
            error_code=NO_ACTIVE_RISK_EVIDENCE,
        )


@dataclass(frozen=True)
class PublicationGateDecision:
    steps: tuple[GateStep, ...]
    can_save_draft: bool
    can_enter_pending_publication: bool
    warnings: tuple[str, ...] = ()
    fact_issues: tuple[ClaimIssue, ...] = ()
    risk_result: RiskScanResult | None = None
    error_code: str | None = None


def _valid_structure(draft: DraftForPublication) -> bool:
    return bool(
        draft.title.strip()
        and draft.copy_text.strip()
        and draft.risk_rule_version.strip()
    )


def evaluate_publication_gate(
    draft: DraftForPublication,
    *,
    confirmed_facts: dict[str, str],
    risk_scanner: RiskScanner,
) -> PublicationGateDecision:
    steps = [GateStep.STRUCTURE_VALIDATION]
    if not _valid_structure(draft):
        return PublicationGateDecision(
            steps=tuple(steps),
            can_save_draft=False,
            can_enter_pending_publication=False,
            error_code="INVALID_GENERATION_STRUCTURE",
        )

    steps.append(GateStep.FACT_RECHECK)
    verification = verify_generated_claims(
        list(draft.claims),
        confirmed_facts=confirmed_facts,
    )
    warnings: list[str] = []
    if not confirmed_facts:
        warnings.append("无事实资料约束")
    if any(not issue.high_risk for issue in verification.issues):
        warnings.append("存在低风险事实差异，请人工复核")
    high_risk_fact_conflict = not verification.can_enter_pending_publication

    steps.append(GateStep.RISK_SCAN)
    try:
        risk_result = risk_scanner.scan(
            RiskScanInput(
                title=draft.title,
                copy=draft.copy_text,
                cover_text=draft.cover_text,
                platform=draft.platform,
                rule_version=draft.risk_rule_version,
            )
        )
    except Exception:
        return PublicationGateDecision(
            steps=tuple(steps),
            can_save_draft=False,
            can_enter_pending_publication=False,
            warnings=tuple(warnings),
            fact_issues=verification.issues,
            error_code="RISK_SCAN_FAILED",
        )

    high_risk_finding = any(
        finding.severity in {RiskSeverity.HIGH, RiskSeverity.CRITICAL}
        for finding in risk_result.findings
    )
    if not risk_result.evidence_available:
        warnings.append("未检索到有效风控证据")

    steps.append(GateStep.SAVE_DRAFT)
    can_enter_pending = (
        not high_risk_fact_conflict
        and not high_risk_finding
        and risk_result.evidence_available
    )
    error_code: str | None = None
    if high_risk_fact_conflict:
        error_code = FACT_CONFLICT
    elif high_risk_finding:
        error_code = "RISK_REVIEW_REQUIRED"
    elif not risk_result.evidence_available:
        error_code = NO_ACTIVE_RISK_EVIDENCE

    return PublicationGateDecision(
        steps=tuple(steps),
        can_save_draft=True,
        can_enter_pending_publication=can_enter_pending,
        warnings=tuple(warnings),
        fact_issues=verification.issues,
        risk_result=risk_result,
        error_code=error_code,
    )
