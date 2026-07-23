from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.security import WorkspaceContext
from app.modules.content.account_models import Platform, PlatformAccount
from app.modules.content.models import AssetCategory, Content, ContentAsset
from app.modules.metrics.models import ContentType
from app.modules.risk_rag.citations import CitationRequest
from app.modules.risk_rag.models import (
    ImmutableRiskScanError,
    RiskDocumentScope,
    RiskScan,
    RiskScanStatus,
    RiskSourceLevel,
)
from app.modules.risk_rag.retrieval import (
    EvidenceBundle,
    EvidenceChunk,
    RetrievalFilter,
)
from app.modules.risk_rag.rules import (
    RuleDisposition,
    RuleMatch,
    RuleScope,
    RuleSeverity,
)
from app.modules.risk_rag.scanner import (
    RISK_SCAN_DISCLAIMER,
    IdempotencyConflict,
    MockOcrProvider,
    OcrRegion,
    OcrResult,
    OcrStatus,
    RagRiskProposal,
    RiskFindingOrigin,
    RiskRegion,
    RiskScanInput,
    RiskScanNode,
    RiskScanPipeline,
    RiskScanService,
    RiskScanExecutionFailed,
    RiskScanVersions,
    ScanSeverity,
)
from app.modules.workspace.models import Workspace
from app.modules.workspace.permissions import PermissionDenied


NOW = datetime(2026, 7, 23, 8, tzinfo=UTC)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        yield database_session


def _filter(
    workspace_id: UUID,
    *,
    platform: Platform = Platform.DOUYIN,
) -> RetrievalFilter:
    return RetrievalFilter(
        workspace_id=workspace_id,
        platform=platform,
        as_of=NOW,
        embedding_model_id="mock-risk-embedding",
        embedding_version="embed-v1",
        embedding_dimension=3,
    )


def _evidence(
    workspace_id: UUID,
    *,
    source_level: RiskSourceLevel = RiskSourceLevel.S1,
    text: str = "SYNTHETIC_CONTEXT_RISK 需要补充限定说明。",
) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_title="人工合成扫描证据",
        source_level=source_level,
        source_url="https://example.invalid/synthetic-scan-evidence",
        private_document_id=None,
        document_version=3,
        effective_at=NOW,
        platform=Platform.DOUYIN,
        workspace_id=None,
        scope=RiskDocumentScope.PUBLIC,
        source_location="人工条款 3",
        untrusted_text=text,
        similarity=0.95,
    )


def _bundle(
    workspace_id: UUID,
    *items: EvidenceChunk,
) -> EvidenceBundle:
    return EvidenceBundle(
        retrieval_filter=_filter(workspace_id),
        evidence=tuple(items),
    )


class RecordingRules:
    def __init__(
        self,
        events: list[str],
        matches: tuple[RuleMatch, ...] = (),
    ) -> None:
        self.events = events
        self.matches = matches
        self.cover_text = ""

    def scan(self, *, platform, title, body, cover_text):
        self.events.append("rules")
        self.cover_text = cover_text
        return list(self.matches)


class RecordingRetriever:
    def __init__(
        self,
        events: list[str],
        bundle: EvidenceBundle,
    ) -> None:
        self.events = events
        self.bundle = bundle
        self.received_filter: RetrievalFilter | None = None

    def retrieve(self, *, retrieval_filter, query_vector, top_k):
        self.events.append("retrieval")
        self.received_filter = retrieval_filter
        assert tuple(query_vector) == (1.0, 0.0, 0.0)
        assert top_k == 8
        return self.bundle


class RecordingRag:
    def __init__(
        self,
        events: list[str],
        proposals: tuple[RagRiskProposal, ...] = (),
        *,
        fail: bool = False,
    ) -> None:
        self.events = events
        self.proposals = proposals
        self.fail = fail

    def assess(self, *, scan_input, evidence_bundle):
        self.events.append("rag")
        if self.fail:
            raise RuntimeError("synthetic rag outage")
        return self.proposals


class FixedQueryEmbedder:
    model_id = "mock-risk-embedding"
    version = "embed-v1"
    dimension = 3

    def embed(self, text: str) -> tuple[float, ...]:
        assert text
        return (1.0, 0.0, 0.0)


def _versions(
    *,
    rule_version: str = "rules-v1",
    evidence_version: str = "evidence-v1",
) -> RiskScanVersions:
    return RiskScanVersions(
        rule_version=rule_version,
        evidence_version=evidence_version,
        embedding_model_id="mock-risk-embedding",
        embedding_version="embed-v1",
        embedding_dimension=3,
        rag_model_version="mock-rag-v1",
        scanner_version="scanner-v1",
    )


def _input(
    workspace_id: UUID,
    *,
    account_id: UUID | None = None,
    content_id: UUID | None = None,
    cover_asset_id: UUID | None = None,
    title: str = "人工合成标题",
    body: str = "人工合成正文",
    ocr: OcrResult | None = None,
    idempotency_key: str = "scan-key-1",
    versions: RiskScanVersions | None = None,
    node: RiskScanNode = RiskScanNode.AFTER_INGESTION,
) -> RiskScanInput:
    return RiskScanInput(
        workspace_id=workspace_id,
        account_id=account_id or uuid4(),
        content_id=content_id or uuid4(),
        cover_asset_id=cover_asset_id,
        platform=Platform.DOUYIN,
        node=node,
        title=title,
        body=body,
        ocr=ocr or OcrResult(status=OcrStatus.EMPTY, regions=()),
        idempotency_key=idempotency_key,
        versions=versions or _versions(),
        requested_at=NOW,
    )


def _pipeline(
    *,
    workspace_id: UUID,
    rules: RecordingRules,
    retriever: RecordingRetriever,
    rag: RecordingRag,
) -> RiskScanPipeline:
    return RiskScanPipeline(
        rule_engine=rules,
        retriever=retriever,
        query_embedder=FixedQueryEmbedder(),
        rag_assessor=rag,
        now=lambda: NOW,
    )


def _high_rule_match(
    evidence_document_id: UUID | None = None,
) -> RuleMatch:
    return RuleMatch(
        rule_id="synthetic-high-rule",
        severity=RuleSeverity.HIGH,
        disposition=RuleDisposition.PROHIBIT,
        scope=RuleScope.COVER_TEXT,
        matched_pattern="SYNTHETIC_HIGH",
        rule_set_version="rules-v1",
        evidence_document_ids=(
            evidence_document_id or uuid4(),
        ),
    )


def test_high_confidence_ocr_enters_rules_and_rag_after_rules() -> None:
    workspace_id = uuid4()
    events: list[str] = []
    item = _evidence(workspace_id)
    rules = RecordingRules(events, (_high_rule_match(item.document_id),))
    retriever = RecordingRetriever(events, _bundle(workspace_id, item))
    rag = RecordingRag(events)
    scan_input = _input(
        workspace_id,
        ocr=OcrResult(
            status=OcrStatus.SUCCEEDED,
            regions=(
                OcrRegion(
                    text="SYNTHETIC_HIGH",
                    bbox=(0.1, 0.2, 0.8, 0.3),
                    confidence=0.97,
                ),
            ),
        ),
    )

    result = _pipeline(
        workspace_id=workspace_id,
        rules=rules,
        retriever=retriever,
        rag=rag,
    ).run(scan_input)

    assert events == ["rules", "retrieval", "rag"]
    assert rules.cover_text == "SYNTHETIC_HIGH"
    assert result.findings[0].region is RiskRegion.COVER
    assert result.findings[0].ocr_bbox == (0.1, 0.2, 0.8, 0.3)
    assert result.findings[0].ocr_confidence == 0.97
    assert result.findings[0].requires_human_review is False


def test_low_confidence_high_risk_ocr_is_explicit_review_candidate() -> None:
    workspace_id = uuid4()
    events: list[str] = []
    rules = RecordingRules(events, (_high_rule_match(),))
    pipeline = _pipeline(
        workspace_id=workspace_id,
        rules=rules,
        retriever=RecordingRetriever(events, _bundle(workspace_id)),
        rag=RecordingRag(events),
    )

    result = pipeline.run(
        _input(
            workspace_id,
            ocr=OcrResult(
                status=OcrStatus.SUCCEEDED,
                regions=(
                    OcrRegion(
                        text="SYNTHETIC_HIGH",
                        bbox=(0.0, 0.0, 0.4, 0.2),
                        confidence=0.42,
                    ),
                ),
            ),
        )
    )

    finding = result.findings[0]
    assert finding.severity is ScanSeverity.HIGH
    assert finding.requires_human_review is True
    assert finding.deterministic_confirmed is False
    assert finding.ocr_confidence == 0.42
    assert "OCR_LOW_CONFIDENCE" in result.diagnostics


@pytest.mark.parametrize(
    "ocr",
    [
        OcrResult(status=OcrStatus.EMPTY, regions=()),
        OcrResult(status=OcrStatus.FAILED, regions=()),
        OcrResult(status=OcrStatus.UNAVAILABLE, regions=()),
    ],
)
def test_missing_ocr_still_scans_title_and_body(ocr: OcrResult) -> None:
    workspace_id = uuid4()
    events: list[str] = []
    title_match = RuleMatch(
        rule_id="synthetic-title",
        severity=RuleSeverity.MEDIUM,
        disposition=RuleDisposition.FLAG,
        scope=RuleScope.TITLE,
        matched_pattern="SYNTHETIC_TITLE",
        rule_set_version="rules-v1",
        evidence_document_ids=(uuid4(),),
    )
    rules = RecordingRules(events, (title_match,))

    result = _pipeline(
        workspace_id=workspace_id,
        rules=rules,
        retriever=RecordingRetriever(events, _bundle(workspace_id)),
        rag=RecordingRag(events),
    ).run(
        _input(
            workspace_id,
            title="SYNTHETIC_TITLE",
            body="正文仍需扫描",
            ocr=ocr,
        )
    )

    assert len(result.findings) == 1
    assert result.findings[0].region is RiskRegion.TITLE
    assert result.ocr_status is ocr.status


def test_mock_ocr_is_deterministic_and_has_no_external_dependency() -> None:
    expected = OcrResult(
        status=OcrStatus.SUCCEEDED,
        regions=(
            OcrRegion(
                text="人工合成 OCR",
                bbox=(0.1, 0.1, 0.9, 0.2),
                confidence=0.88,
            ),
        ),
    )
    provider = MockOcrProvider(expected)

    assert provider.extract(b"synthetic-cover") == expected
    assert provider.extract(b"synthetic-cover") == expected
    assert provider.call_count == 2


def test_rag_cannot_lower_rule_and_duplicate_keeps_all_evidence() -> None:
    workspace_id = uuid4()
    events: list[str] = []
    first = _evidence(workspace_id)
    second = _evidence(
        workspace_id,
        text="SYNTHETIC_CONTEXT_RISK 需要人工复核。",
    )
    rule_match = RuleMatch(
        rule_id="synthetic-overlap",
        severity=RuleSeverity.HIGH,
        disposition=RuleDisposition.PROHIBIT,
        scope=RuleScope.BODY,
        matched_pattern="SYNTHETIC_CONTEXT_RISK",
        rule_set_version="rules-v1",
        evidence_document_ids=(first.document_id,),
    )
    proposal = RagRiskProposal(
        risk_type="synthetic-overlap",
        severity=ScanSeverity.LOW,
        matched_content="SYNTHETIC_CONTEXT_RISK",
        region=RiskRegion.BODY,
        reason="SYNTHETIC_CONTEXT_RISK",
        suggestion="补充限定信息",
        conclusion="SYNTHETIC_CONTEXT_RISK",
        citations=(
            CitationRequest(
                chunk_id=second.chunk_id,
                excerpt="SYNTHETIC_CONTEXT_RISK",
            ),
        ),
    )

    result = _pipeline(
        workspace_id=workspace_id,
        rules=RecordingRules(events, (rule_match,)),
        retriever=RecordingRetriever(
            events,
            _bundle(workspace_id, first, second),
        ),
        rag=RecordingRag(events, (proposal,)),
    ).run(_input(workspace_id, body="SYNTHETIC_CONTEXT_RISK"))

    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.severity is ScanSeverity.HIGH
    assert finding.origin is RiskFindingOrigin.DETERMINISTIC_AND_RAG
    assert set(finding.evidence_document_ids) == {
        first.document_id,
        second.document_id,
    }
    assert {citation.chunk_id for citation in finding.citations} == {
        second.chunk_id
    }


def test_s5_alone_cannot_support_high_risk_rag_conclusion() -> None:
    workspace_id = uuid4()
    events: list[str] = []
    s5 = _evidence(workspace_id, source_level=RiskSourceLevel.S5)
    proposal = RagRiskProposal(
        risk_type="synthetic-s5",
        severity=ScanSeverity.HIGH,
        matched_content="SYNTHETIC_CONTEXT_RISK",
        region=RiskRegion.BODY,
        reason="SYNTHETIC_CONTEXT_RISK",
        suggestion="人工复核",
        conclusion="SYNTHETIC_CONTEXT_RISK",
        citations=(
            CitationRequest(
                chunk_id=s5.chunk_id,
                excerpt="SYNTHETIC_CONTEXT_RISK",
            ),
        ),
    )

    result = _pipeline(
        workspace_id=workspace_id,
        rules=RecordingRules(events),
        retriever=RecordingRetriever(events, _bundle(workspace_id, s5)),
        rag=RecordingRag(events, (proposal,)),
    ).run(_input(workspace_id))

    assert result.findings[0].severity is ScanSeverity.MEDIUM
    assert result.findings[0].requires_human_review is True
    assert "S5_HIGH_RISK_DOWNGRADED" in result.diagnostics


def test_no_active_evidence_or_rag_outage_keeps_deterministic_results() -> None:
    workspace_id = uuid4()
    events: list[str] = []
    rule_match = _high_rule_match()

    no_evidence = _pipeline(
        workspace_id=workspace_id,
        rules=RecordingRules(events, (rule_match,)),
        retriever=RecordingRetriever(events, _bundle(workspace_id)),
        rag=RecordingRag(events, fail=True),
    ).run(_input(workspace_id))

    assert len(no_evidence.findings) == 1
    assert no_evidence.findings[0].citations == ()
    assert no_evidence.error_code == "NO_ACTIVE_RISK_EVIDENCE"
    assert "RAG_UNAVAILABLE" not in no_evidence.diagnostics
    assert no_evidence.disclaimer == RISK_SCAN_DISCLAIMER

    active_item = _evidence(workspace_id)
    events.clear()
    unavailable = _pipeline(
        workspace_id=workspace_id,
        rules=RecordingRules(events, (rule_match,)),
        retriever=RecordingRetriever(
            events,
            _bundle(workspace_id, active_item),
        ),
        rag=RecordingRag(events, fail=True),
    ).run(_input(workspace_id, idempotency_key="rag-outage"))

    assert len(unavailable.findings) == 1
    assert unavailable.findings[0].origin is RiskFindingOrigin.DETERMINISTIC
    assert unavailable.error_code == "RAG_UNAVAILABLE"
    assert "RAG_UNAVAILABLE" in unavailable.diagnostics


def test_result_contains_traceable_versions_and_complete_finding_shape() -> None:
    workspace_id = uuid4()
    events: list[str] = []
    item = _evidence(workspace_id)
    proposal = RagRiskProposal(
        risk_type="context-risk",
        severity=ScanSeverity.MEDIUM,
        matched_content="SYNTHETIC_CONTEXT_RISK",
        region=RiskRegion.BODY,
        reason="SYNTHETIC_CONTEXT_RISK",
        suggestion="增加限制条件",
        conclusion="SYNTHETIC_CONTEXT_RISK",
        citations=(
            CitationRequest(
                chunk_id=item.chunk_id,
                excerpt="SYNTHETIC_CONTEXT_RISK",
            ),
        ),
    )
    versions = _versions()

    result = _pipeline(
        workspace_id=workspace_id,
        rules=RecordingRules(events),
        retriever=RecordingRetriever(events, _bundle(workspace_id, item)),
        rag=RecordingRag(events, (proposal,)),
    ).run(_input(workspace_id, versions=versions))

    finding = result.findings[0]
    assert finding.risk_type == "context-risk"
    assert finding.matched_content == "SYNTHETIC_CONTEXT_RISK"
    assert finding.evidence_document_ids == (item.document_id,)
    assert finding.reason
    assert finding.suggestion
    assert result.versions == versions
    assert result.disclaimer == "辅助判断，不保证通过平台审核"


def _content_graph(
    session: Session,
) -> tuple[Workspace, PlatformAccount, Content, ContentAsset]:
    workspace = Workspace(name="scan-history-workspace")
    account = PlatformAccount(
        workspace_id=workspace.id,
        platform=Platform.DOUYIN,
        name="scan-account",
    )
    content = Content(
        workspace_id=workspace.id,
        account_id=account.id,
        platform=Platform.DOUYIN,
        title="人工合成标题",
        body="人工合成正文",
        objective_profile_id=uuid4(),
        benchmark_profile_id=uuid4(),
        content_type=ContentType.VIDEO,
    )
    asset = ContentAsset(
        workspace_id=workspace.id,
        content_id=content.id,
        category=AssetCategory.COVER,
        object_key=f"workspaces/{workspace.id}/synthetic-cover.png",
        file_name="synthetic-cover.png",
        mime_type="image/png",
        size=100,
    )
    session.add_all([workspace, account, content, asset])
    session.commit()
    return workspace, account, content, asset


def _empty_pipeline(workspace_id: UUID) -> RiskScanPipeline:
    events: list[str] = []
    return _pipeline(
        workspace_id=workspace_id,
        rules=RecordingRules(events),
        retriever=RecordingRetriever(events, _bundle(workspace_id)),
        rag=RecordingRag(events),
    )


def test_scan_history_is_immutable_idempotent_and_version_linked(
    session: Session,
) -> None:
    workspace, account, content, asset = _content_graph(session)
    context = WorkspaceContext(
        workspace_id=workspace.id,
        member_id=None,
        role="editor",
    )
    service = RiskScanService(session, context=context)
    first_input = _input(
        workspace.id,
        account_id=account.id,
        content_id=content.id,
        cover_asset_id=asset.id,
    )

    first = service.execute(
        first_input,
        pipeline=_empty_pipeline(workspace.id),
    )
    duplicate = service.execute(
        first_input,
        pipeline=_empty_pipeline(workspace.id),
    )
    second = service.execute(
        _input(
            workspace.id,
            account_id=account.id,
            content_id=content.id,
            cover_asset_id=asset.id,
            title="修改后的人工合成标题",
            idempotency_key="scan-key-2",
        ),
        pipeline=_empty_pipeline(workspace.id),
    )
    third = service.execute(
        _input(
            workspace.id,
            account_id=account.id,
            content_id=content.id,
            cover_asset_id=asset.id,
            title="修改后的人工合成标题",
            idempotency_key="scan-key-3",
            versions=_versions(rule_version="rules-v2"),
        ),
        pipeline=_empty_pipeline(workspace.id),
    )
    session.commit()

    scans = list(
        session.scalars(
            select(RiskScan).order_by(RiskScan.created_at, RiskScan.id)
        )
    )
    assert duplicate.id == first.id
    assert len(scans) == 3
    assert second.previous_scan_id == first.id
    assert third.previous_scan_id == second.id
    assert first.input_snapshot["title"] == "人工合成标题"
    assert second.input_snapshot["title"] == "修改后的人工合成标题"
    assert first.status is RiskScanStatus.SUCCEEDED
    assert all(scan.result is not None for scan in scans)


def test_same_idempotency_key_with_changed_input_is_rejected(
    session: Session,
) -> None:
    workspace, account, content, asset = _content_graph(session)
    service = RiskScanService(
        session,
        context=WorkspaceContext(
            workspace_id=workspace.id,
            member_id=None,
            role="admin",
        ),
    )
    service.execute(
        _input(
            workspace.id,
            account_id=account.id,
            content_id=content.id,
            cover_asset_id=asset.id,
        ),
        pipeline=_empty_pipeline(workspace.id),
    )

    with pytest.raises(IdempotencyConflict):
        service.execute(
            _input(
                workspace.id,
                account_id=account.id,
                content_id=content.id,
                cover_asset_id=asset.id,
                title="changed",
            ),
            pipeline=_empty_pipeline(workspace.id),
        )


def test_failed_scan_is_persisted_as_failed_and_never_as_success(
    session: Session,
) -> None:
    workspace, account, content, asset = _content_graph(session)
    service = RiskScanService(
        session,
        context=WorkspaceContext(
            workspace_id=workspace.id,
            member_id=None,
            role="editor",
        ),
    )

    class FailingPipeline:
        def run(self, scan_input):
            raise ValueError("synthetic invalid citation")

    with pytest.raises(RiskScanExecutionFailed):
        service.execute(
            _input(
                workspace.id,
                account_id=account.id,
                content_id=content.id,
                cover_asset_id=asset.id,
            ),
            pipeline=FailingPipeline(),  # type: ignore[arg-type]
        )
    failed = session.scalar(select(RiskScan))

    assert failed is not None
    assert failed.status is RiskScanStatus.FAILED
    assert failed.result is None
    assert failed.error_code == "RISK_SCAN_VALIDATION_FAILED"


def test_persisted_scan_cannot_be_overwritten_or_deleted(
    session: Session,
) -> None:
    workspace, account, content, asset = _content_graph(session)
    scan = RiskScanService(
        session,
        context=WorkspaceContext(
            workspace_id=workspace.id,
            member_id=None,
            role="admin",
        ),
    ).execute(
        _input(
            workspace.id,
            account_id=account.id,
            content_id=content.id,
            cover_asset_id=asset.id,
        ),
        pipeline=_empty_pipeline(workspace.id),
    )
    session.commit()

    scan.result = {"forged": True}
    with pytest.raises(ImmutableRiskScanError):
        session.commit()
    session.rollback()
    persisted = session.get(RiskScan, scan.id)
    assert persisted is not None
    session.delete(persisted)
    with pytest.raises(ImmutableRiskScanError):
        session.commit()


def test_viewer_cannot_trigger_and_foreign_asset_is_not_found(
    session: Session,
) -> None:
    workspace, account, content, _ = _content_graph(session)
    other = Workspace(name="other-scan-workspace")
    foreign_asset = ContentAsset(
        workspace_id=other.id,
        content_id=content.id,
        category=AssetCategory.COVER,
        object_key=f"workspaces/{other.id}/foreign-cover.png",
        file_name="foreign-cover.png",
        mime_type="image/png",
        size=100,
    )
    session.add_all([other, foreign_asset])
    session.commit()
    scan_input = _input(
        workspace.id,
        account_id=account.id,
        content_id=content.id,
        cover_asset_id=foreign_asset.id,
    )

    with pytest.raises(PermissionDenied):
        RiskScanService(
            session,
            context=WorkspaceContext(
                workspace_id=workspace.id,
                member_id=None,
                role="viewer",
            ),
        ).execute(
            scan_input,
            pipeline=_empty_pipeline(workspace.id),
        )
    with pytest.raises(LookupError, match="cover asset"):
        RiskScanService(
            session,
            context=WorkspaceContext(
                workspace_id=workspace.id,
                member_id=None,
                role="editor",
            ),
        ).execute(
            scan_input,
            pipeline=_empty_pipeline(workspace.id),
        )
