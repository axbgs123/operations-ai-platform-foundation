import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.content.account_models import Platform, PlatformAccount
from app.modules.content.models import AssetCategory, Content, ContentAsset
from app.modules.risk_rag.citations import (
    Citation,
    CitationRequest,
    ProposedRiskConclusion,
    validate_cited_result,
)
from app.modules.generation.publication_gate import (
    RiskFinding as GateRiskFinding,
    RiskScanInput as GateRiskScanInput,
    RiskScanResult as GateRiskScanResult,
    RiskSeverity as GateRiskSeverity,
)
from app.modules.risk_rag.models import (
    RiskScan,
    RiskScanNode,
    RiskScanStatus,
    RiskSourceLevel,
)
from app.modules.risk_rag.retrieval import (
    NO_ACTIVE_RISK_EVIDENCE,
    EvidenceBundle,
    RetrievalFilter,
    RiskEvidenceRetriever,
)
from app.modules.risk_rag.rules import (
    RuleEngine,
    RuleMatch,
    RuleScope,
    RuleSeverity,
)
from app.modules.workspace.permissions import Permission, require_permission


RISK_SCAN_DISCLAIMER = "辅助判断，不保证通过平台审核"
OCR_CONFIDENCE_THRESHOLD = 0.8


class OcrStatus(StrEnum):
    SUCCEEDED = "succeeded"
    EMPTY = "empty"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class RiskRegion(StrEnum):
    TITLE = "title"
    BODY = "body"
    COVER = "cover"


class ScanSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskFindingOrigin(StrEnum):
    DETERMINISTIC = "deterministic"
    RAG = "rag"
    DETERMINISTIC_AND_RAG = "deterministic_and_rag"


class ImmutableScanModel(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
    )


class OcrRegion(ImmutableScanModel):
    text: str = Field(min_length=1, max_length=2_000)
    bbox: tuple[float, float, float, float]
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_bbox(self):
        x, y, width, height = self.bbox
        if any(value < 0 or value > 1 for value in self.bbox):
            raise ValueError("OCR coordinates must be normalized")
        if width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
            raise ValueError("OCR bounding box is invalid")
        return self


class OcrResult(ImmutableScanModel):
    status: OcrStatus
    regions: tuple[OcrRegion, ...]
    confidence_source: str = "mock"
    requires_human_review: bool = False

    @model_validator(mode="after")
    def status_matches_regions(self):
        if self.status is OcrStatus.SUCCEEDED and not self.regions:
            raise ValueError("successful OCR requires regions")
        if self.status is not OcrStatus.SUCCEEDED and self.regions:
            raise ValueError("non-successful OCR cannot include regions")
        return self


class RiskScanVersions(ImmutableScanModel):
    rule_version: str = Field(min_length=1, max_length=160)
    evidence_version: str = Field(min_length=1, max_length=160)
    embedding_model_id: str = Field(min_length=1, max_length=160)
    embedding_version: str = Field(min_length=1, max_length=80)
    embedding_dimension: int = Field(gt=0)
    rag_model_version: str = Field(min_length=1, max_length=160)
    scanner_version: str = Field(min_length=1, max_length=160)
    ocr_provider: str = Field(default="mock", min_length=1, max_length=80)
    ocr_model_id: str = Field(
        default="mock-ocr-v1", min_length=1, max_length=160
    )
    ocr_contract_version: str = Field(
        default="mock-ocr-v1", min_length=1, max_length=80
    )
    ocr_config_version: str = Field(
        default="mock-static-v1", min_length=1, max_length=80
    )


class RiskScanInput(ImmutableScanModel):
    workspace_id: UUID
    account_id: UUID
    content_id: UUID
    cover_asset_id: UUID | None = None
    platform: Platform
    node: RiskScanNode
    title: str = Field(max_length=2_000)
    body: str = Field(max_length=100_000)
    ocr: OcrResult
    idempotency_key: str = Field(min_length=1, max_length=200)
    versions: RiskScanVersions
    requested_at: datetime

    @model_validator(mode="after")
    def aware_request_time(self):
        if self.requested_at.tzinfo is None:
            raise ValueError("requested_at must be timezone-aware")
        return self


class RagRiskProposal(ImmutableScanModel):
    risk_type: str = Field(min_length=1, max_length=160)
    severity: ScanSeverity
    matched_content: str = Field(min_length=1, max_length=2_000)
    region: RiskRegion
    reason: str = Field(min_length=1, max_length=2_000)
    suggestion: str = Field(min_length=1, max_length=2_000)
    conclusion: str = Field(min_length=1, max_length=2_000)
    citations: tuple[CitationRequest, ...]


class RiskFinding(ImmutableScanModel):
    risk_type: str
    severity: ScanSeverity
    matched_content: str
    region: RiskRegion
    ocr_bbox: tuple[float, float, float, float] | None = None
    ocr_confidence: float | None = None
    evidence_document_ids: tuple[UUID, ...] = ()
    citations: tuple[Citation, ...] = ()
    reason: str
    suggestion: str
    origin: RiskFindingOrigin
    requires_human_review: bool = False
    deterministic_confirmed: bool = False


class RiskScanOutput(ImmutableScanModel):
    findings: tuple[RiskFinding, ...]
    ocr_status: OcrStatus
    diagnostics: tuple[str, ...]
    error_code: str | None
    versions: RiskScanVersions
    scanned_at: datetime
    disclaimer: str = RISK_SCAN_DISCLAIMER


class QueryEmbedder(Protocol):
    model_id: str
    version: str
    dimension: int

    def embed(self, text: str) -> tuple[float, ...]: ...


class EvidenceRetriever(Protocol):
    def retrieve(
        self,
        *,
        retrieval_filter: RetrievalFilter,
        query_vector: tuple[float, ...],
        top_k: int,
    ) -> EvidenceBundle: ...


class RagAssessor(Protocol):
    def assess(
        self,
        *,
        scan_input: RiskScanInput,
        evidence_bundle: EvidenceBundle,
    ) -> tuple[RagRiskProposal, ...]: ...


class RuleScanner(Protocol):
    def scan(
        self,
        *,
        platform: Platform,
        title: str,
        body: str,
        cover_text: str,
    ) -> list[RuleMatch]: ...


class MockOcrProvider:
    def __init__(self, result: OcrResult) -> None:
        self._result = result
        self.call_count = 0

    def extract(self, content: bytes) -> OcrResult:
        self.call_count += 1
        return self._result


class MockRiskQueryEmbedder:
    def __init__(
        self,
        *,
        model_id: str,
        version: str,
        dimension: int,
    ) -> None:
        self.model_id = model_id
        self.version = version
        self.dimension = dimension

    def embed(self, text: str) -> tuple[float, ...]:
        digest = hashlib.sha256(text.encode()).digest()
        values = tuple(
            (digest[index % len(digest)] + 1) / 256
            for index in range(self.dimension)
        )
        return values


class EmptyRuleScanner:
    def scan(
        self,
        *,
        platform: Platform,
        title: str,
        body: str,
        cover_text: str,
    ) -> list[RuleMatch]:
        return []


class EmptyRagAssessor:
    def assess(
        self,
        *,
        scan_input: RiskScanInput,
        evidence_bundle: EvidenceBundle,
    ) -> tuple[RagRiskProposal, ...]:
        return ()


class IdempotencyConflict(ValueError):
    pass


class RiskScanExecutionFailed(RuntimeError):
    def __init__(self, scan_id: UUID) -> None:
        super().__init__("risk scan failed deterministic validation")
        self.scan_id = scan_id


def _scope_region(scope: RuleScope) -> RiskRegion:
    return {
        RuleScope.TITLE: RiskRegion.TITLE,
        RuleScope.BODY: RiskRegion.BODY,
        RuleScope.COVER_TEXT: RiskRegion.COVER,
    }[scope]


def _severity(value: RuleSeverity) -> ScanSeverity:
    return ScanSeverity(value.value)


def _ocr_metadata(
    scan_input: RiskScanInput,
    *,
    region: RiskRegion,
    matched_content: str,
) -> tuple[
    tuple[float, float, float, float] | None,
    float | None,
]:
    if region is not RiskRegion.COVER:
        return None, None
    matching = next(
        (
            item
            for item in scan_input.ocr.regions
            if matched_content.casefold() in item.text.casefold()
        ),
        None,
    )
    if matching is None:
        return None, None
    return matching.bbox, matching.confidence


def _merge_findings(
    findings: list[RiskFinding],
) -> tuple[RiskFinding, ...]:
    severity_rank = {
        ScanSeverity.LOW: 0,
        ScanSeverity.MEDIUM: 1,
        ScanSeverity.HIGH: 2,
    }
    merged: dict[tuple[str, str, RiskRegion], RiskFinding] = {}
    for finding in findings:
        key = (
            finding.risk_type,
            finding.matched_content,
            finding.region,
        )
        current = merged.get(key)
        if current is None:
            merged[key] = finding
            continue
        highest = (
            finding
            if severity_rank[finding.severity]
            > severity_rank[current.severity]
            else current
        )
        evidence_ids = tuple(
            dict.fromkeys(
                current.evidence_document_ids
                + finding.evidence_document_ids
            )
        )
        citations = tuple(
            {
                citation.chunk_id: citation
                for citation in current.citations + finding.citations
            }.values()
        )
        merged[key] = highest.model_copy(
            update={
                "evidence_document_ids": evidence_ids,
                "citations": citations,
                "origin": RiskFindingOrigin.DETERMINISTIC_AND_RAG,
                "requires_human_review": (
                    current.requires_human_review
                    or finding.requires_human_review
                ),
                "deterministic_confirmed": (
                    current.deterministic_confirmed
                    or finding.deterministic_confirmed
                ),
            }
        )
    return tuple(merged.values())


class RiskScanPipeline:
    def __init__(
        self,
        *,
        rule_engine: RuleScanner | RuleEngine,
        retriever: EvidenceRetriever,
        query_embedder: QueryEmbedder,
        rag_assessor: RagAssessor,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._rule_engine = rule_engine
        self._retriever = retriever
        self._query_embedder = query_embedder
        self._rag_assessor = rag_assessor
        self._now = now or (lambda: datetime.now(UTC))

    def run(self, scan_input: RiskScanInput) -> RiskScanOutput:
        versions = scan_input.versions
        if (
            self._query_embedder.model_id != versions.embedding_model_id
            or self._query_embedder.version != versions.embedding_version
            or self._query_embedder.dimension
            != versions.embedding_dimension
        ):
            raise ValueError("query embedder does not match scan versions")

        cover_text = "\n".join(
            region.text for region in scan_input.ocr.regions
        )
        rule_matches = self._rule_engine.scan(
            platform=scan_input.platform,
            title=scan_input.title,
            body=scan_input.body,
            cover_text=cover_text,
        )
        findings: list[RiskFinding] = []
        diagnostics: list[str] = []
        for match in rule_matches:
            region = _scope_region(match.scope)
            bbox, confidence = _ocr_metadata(
                scan_input,
                region=region,
                matched_content=match.matched_pattern,
            )
            low_confidence = (
                region is RiskRegion.COVER
                and confidence is not None
                and confidence < OCR_CONFIDENCE_THRESHOLD
            )
            if low_confidence:
                diagnostics.append("OCR_LOW_CONFIDENCE")
            findings.append(
                RiskFinding(
                    risk_type=match.rule_id,
                    severity=_severity(match.severity),
                    matched_content=match.matched_pattern,
                    region=region,
                    ocr_bbox=bbox,
                    ocr_confidence=confidence,
                    evidence_document_ids=match.evidence_document_ids,
                    reason="确定性规则检测到人工配置的风险模式。",
                    suggestion="请依据引用规则人工复核并调整相关内容。",
                    origin=RiskFindingOrigin.DETERMINISTIC,
                    requires_human_review=low_confidence,
                    deterministic_confirmed=not low_confidence,
                )
            )

        query_text = "\n".join(
            (scan_input.title, scan_input.body, cover_text)
        )
        retrieval_filter = RetrievalFilter(
            workspace_id=scan_input.workspace_id,
            platform=scan_input.platform,
            as_of=scan_input.requested_at,
            embedding_model_id=versions.embedding_model_id,
            embedding_version=versions.embedding_version,
            embedding_dimension=versions.embedding_dimension,
        )
        bundle = self._retriever.retrieve(
            retrieval_filter=retrieval_filter,
            query_vector=self._query_embedder.embed(query_text),
            top_k=8,
        )
        error_code: str | None = None
        if not bundle.evidence:
            error_code = NO_ACTIVE_RISK_EVIDENCE
        else:
            try:
                proposals = self._rag_assessor.assess(
                    scan_input=scan_input,
                    evidence_bundle=bundle,
                )
            except Exception:
                diagnostics.append("RAG_UNAVAILABLE")
                proposals = ()
                error_code = "RAG_UNAVAILABLE"
            by_chunk = bundle.by_chunk_id()
            for proposal in proposals:
                validation = validate_cited_result(
                    bundle,
                    ProposedRiskConclusion(
                        conclusion=proposal.conclusion,
                        citations=proposal.citations,
                    ),
                )
                if not validation.success:
                    raise ValueError("RAG citation validation failed")
                cited_items = [
                    by_chunk[citation.chunk_id]
                    for citation in validation.citations
                ]
                severity = proposal.severity
                requires_review = False
                if (
                    severity is ScanSeverity.HIGH
                    and cited_items
                    and all(
                        item.source_level is RiskSourceLevel.S5
                        for item in cited_items
                    )
                ):
                    severity = ScanSeverity.MEDIUM
                    requires_review = True
                    diagnostics.append("S5_HIGH_RISK_DOWNGRADED")
                bbox, confidence = _ocr_metadata(
                    scan_input,
                    region=proposal.region,
                    matched_content=proposal.matched_content,
                )
                if (
                    proposal.region is RiskRegion.COVER
                    and confidence is not None
                    and confidence < OCR_CONFIDENCE_THRESHOLD
                ):
                    requires_review = True
                    diagnostics.append("OCR_LOW_CONFIDENCE")
                findings.append(
                    RiskFinding(
                        risk_type=proposal.risk_type,
                        severity=severity,
                        matched_content=proposal.matched_content,
                        region=proposal.region,
                        ocr_bbox=bbox,
                        ocr_confidence=confidence,
                        evidence_document_ids=tuple(
                            dict.fromkeys(
                                item.document_id for item in cited_items
                            )
                        ),
                        citations=validation.citations,
                        reason=proposal.reason,
                        suggestion=proposal.suggestion,
                        origin=RiskFindingOrigin.RAG,
                        requires_human_review=requires_review,
                        deterministic_confirmed=False,
                    )
                )
        return RiskScanOutput(
            findings=_merge_findings(findings),
            ocr_status=scan_input.ocr.status,
            diagnostics=tuple(dict.fromkeys(diagnostics)),
            error_code=error_code,
            versions=versions,
            scanned_at=self._now(),
        )


def _input_fingerprint(scan_input: RiskScanInput) -> str:
    payload = scan_input.model_dump(mode="json", exclude={"idempotency_key"})
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class RiskScanService:
    def __init__(
        self,
        session: Session,
        *,
        context: WorkspaceContext,
    ) -> None:
        self._session = session
        self._context = context

    def _validate_assets(self, scan_input: RiskScanInput) -> None:
        if scan_input.workspace_id != self._context.workspace_id:
            raise LookupError("workspace not found")
        account = self._session.scalar(
            select(PlatformAccount).where(
                PlatformAccount.id == scan_input.account_id,
                PlatformAccount.workspace_id == self._context.workspace_id,
                PlatformAccount.platform == scan_input.platform,
            )
        )
        if account is None:
            raise LookupError("account not found")
        content = self._session.scalar(
            select(Content).where(
                Content.id == scan_input.content_id,
                Content.workspace_id == self._context.workspace_id,
                Content.account_id == account.id,
                Content.platform == scan_input.platform,
                Content.deleted_at.is_(None),
            )
        )
        if content is None:
            raise LookupError("content not found")
        if scan_input.cover_asset_id is None:
            return
        asset = self._session.scalar(
            select(ContentAsset).where(
                ContentAsset.id == scan_input.cover_asset_id,
                ContentAsset.workspace_id == self._context.workspace_id,
                ContentAsset.content_id == content.id,
                ContentAsset.category == AssetCategory.COVER,
            )
        )
        if asset is None:
            raise LookupError("cover asset not found")

    def execute(
        self,
        scan_input: RiskScanInput,
        *,
        pipeline: RiskScanPipeline,
    ) -> RiskScan:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        self._validate_assets(scan_input)
        fingerprint = _input_fingerprint(scan_input)
        existing = self._session.scalar(
            select(RiskScan).where(
                RiskScan.workspace_id == self._context.workspace_id,
                RiskScan.idempotency_key == scan_input.idempotency_key,
            )
        )
        if existing is not None:
            if existing.input_fingerprint != fingerprint:
                raise IdempotencyConflict(
                    "idempotency key already used for different scan input"
                )
            return existing
        previous = self._session.scalar(
            select(RiskScan)
            .where(
                RiskScan.workspace_id == self._context.workspace_id,
                RiskScan.content_id == scan_input.content_id,
            )
            .order_by(RiskScan.created_at.desc(), RiskScan.id.desc())
            .limit(1)
        )
        input_snapshot = scan_input.model_dump(mode="json")
        try:
            output = pipeline.run(scan_input)
        except Exception:
            scan = self._new_record(
                scan_input=scan_input,
                fingerprint=fingerprint,
                input_snapshot=input_snapshot,
                previous=previous,
                status=RiskScanStatus.FAILED,
                result=None,
                error_code="RISK_SCAN_VALIDATION_FAILED",
                diagnostics=["RISK_SCAN_VALIDATION_FAILED"],
            )
            self._session.flush()
            raise RiskScanExecutionFailed(scan.id) from None
        scan = self._new_record(
            scan_input=scan_input,
            fingerprint=fingerprint,
            input_snapshot=input_snapshot,
            previous=previous,
            status=RiskScanStatus.SUCCEEDED,
            result=output.model_dump(mode="json"),
            error_code=output.error_code,
            diagnostics=list(output.diagnostics),
        )
        self._session.flush()
        return scan

    def _new_record(
        self,
        *,
        scan_input: RiskScanInput,
        fingerprint: str,
        input_snapshot: dict[str, object],
        previous: RiskScan | None,
        status: RiskScanStatus,
        result: dict[str, object] | None,
        error_code: str | None,
        diagnostics: list[str],
    ) -> RiskScan:
        versions = scan_input.versions
        scan = RiskScan(
            workspace_id=self._context.workspace_id,
            account_id=scan_input.account_id,
            content_id=scan_input.content_id,
            cover_asset_id=scan_input.cover_asset_id,
            previous_scan_id=previous.id if previous is not None else None,
            requested_by=self._context.member_id,
            platform=scan_input.platform,
            node=scan_input.node,
            status=status,
            idempotency_key=scan_input.idempotency_key,
            input_fingerprint=fingerprint,
            input_snapshot=input_snapshot,
            result=result,
            error_code=error_code,
            diagnostics=diagnostics,
            rule_version=versions.rule_version,
            evidence_version=versions.evidence_version,
            embedding_model_id=versions.embedding_model_id,
            embedding_version=versions.embedding_version,
            embedding_dimension=versions.embedding_dimension,
            rag_model_version=versions.rag_model_version,
            scanner_version=versions.scanner_version,
            ocr_provider=versions.ocr_provider,
            ocr_model_id=versions.ocr_model_id,
            ocr_contract_version=versions.ocr_contract_version,
            ocr_config_version=versions.ocr_config_version,
        )
        self._session.add(scan)
        return scan

    def get(self, scan_id: UUID) -> RiskScan:
        require_permission(self._context.role, Permission.READ_CONTENT)
        scan = self._session.scalar(
            select(RiskScan).where(
                RiskScan.id == scan_id,
                RiskScan.workspace_id == self._context.workspace_id,
            )
        )
        if scan is None:
            raise LookupError("risk scan not found")
        return scan

    def history(self, content_id: UUID) -> list[RiskScan]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        return list(
            self._session.scalars(
                select(RiskScan)
                .where(
                    RiskScan.workspace_id == self._context.workspace_id,
                    RiskScan.content_id == content_id,
                )
                .order_by(RiskScan.created_at.desc(), RiskScan.id.desc())
            )
        )


def build_default_pipeline(
    session: Session,
    scan_input: RiskScanInput,
) -> RiskScanPipeline:
    versions = scan_input.versions
    return RiskScanPipeline(
        rule_engine=EmptyRuleScanner(),
        retriever=RiskEvidenceRetriever(session),
        query_embedder=MockRiskQueryEmbedder(
            model_id=versions.embedding_model_id,
            version=versions.embedding_version,
            dimension=versions.embedding_dimension,
        ),
        rag_assessor=EmptyRagAssessor(),
    )


class GenerationRiskScannerAdapter:
    def __init__(
        self,
        *,
        workspace_id: UUID,
        account_id: UUID,
        content_id: UUID,
        ocr: OcrResult,
        versions: RiskScanVersions,
        execute: Callable[[RiskScanInput], RiskScanOutput],
        idempotency_key_factory: Callable[[], str],
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._workspace_id = workspace_id
        self._account_id = account_id
        self._content_id = content_id
        self._ocr = ocr
        self._versions = versions
        self._execute = execute
        self._idempotency_key_factory = idempotency_key_factory
        self._now = now or (lambda: datetime.now(UTC))

    def scan(self, data: GateRiskScanInput) -> GateRiskScanResult:
        output = self._execute(
            RiskScanInput(
                workspace_id=self._workspace_id,
                account_id=self._account_id,
                content_id=self._content_id,
                platform=Platform(data.platform),
                node=RiskScanNode.AFTER_GENERATION,
                title=data.title,
                body=data.copy_text,
                ocr=self._ocr,
                idempotency_key=self._idempotency_key_factory(),
                versions=self._versions.model_copy(
                    update={"rule_version": data.rule_version}
                ),
                requested_at=self._now(),
            )
        )
        findings = tuple(
            GateRiskFinding(
                code=finding.risk_type,
                severity=GateRiskSeverity(finding.severity.value),
                message=finding.reason,
                citations=tuple(
                    str(citation.chunk_id)
                    for citation in finding.citations
                ),
            )
            for finding in output.findings
        )
        return GateRiskScanResult(
            findings=findings,
            evidence_available=output.error_code
            != NO_ACTIVE_RISK_EVIDENCE,
            rule_version=output.versions.rule_version,
            error_code=output.error_code,
        )
