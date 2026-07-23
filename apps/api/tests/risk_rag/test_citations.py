from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.modules.content.account_models import Platform
from app.modules.risk_rag.citations import (
    CitationRequest,
    CitationValidationError,
    ProposedRiskConclusion,
    build_citations,
    require_successful_validation,
    validate_cited_result,
)
from app.modules.risk_rag.models import RiskDocumentScope, RiskSourceLevel
from app.modules.risk_rag.retrieval import (
    EvidenceBundle,
    EvidenceChunk,
    RetrievalFilter,
)


NOW = datetime(2026, 7, 23, 8, tzinfo=UTC)
WORKSPACE_ID = uuid4()
SENSITIVE_BODY = "SYNTHETIC_PRIVATE_BODY_MUST_NOT_ENTER_DIAGNOSTICS"


def _filter() -> RetrievalFilter:
    return RetrievalFilter(
        workspace_id=WORKSPACE_ID,
        platform=Platform.DOUYIN,
        as_of=NOW,
        embedding_model_id="mock-risk-embedding",
        embedding_version="v1",
        embedding_dimension=3,
    )


def _evidence(
    *,
    chunk_id: UUID | None = None,
    platform: Platform = Platform.DOUYIN,
    workspace_id: UUID | None = WORKSPACE_ID,
    scope: RiskDocumentScope = RiskDocumentScope.PRIVATE,
) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id or uuid4(),
        document_id=uuid4(),
        document_title="人工合成风险资料",
        source_level=RiskSourceLevel.S3,
        source_url=None,
        private_document_id="synthetic-private-document",
        document_version=2,
        effective_at=NOW,
        platform=platform,
        workspace_id=workspace_id,
        scope=scope,
        source_location="人工条款 2 / 第 1 段",
        untrusted_text=(
            "人工合成证据说明：SYNTHETIC_RISK_CLAIM 需要人工复核。"
            f"{SENSITIVE_BODY}"
        ),
        similarity=0.91,
    )


def _bundle(item: EvidenceChunk | None = None) -> EvidenceBundle:
    return EvidenceBundle(
        retrieval_filter=_filter(),
        evidence=(item or _evidence(),),
    )


def test_citation_contains_complete_verifiable_provenance() -> None:
    bundle = _bundle()
    item = bundle.evidence[0]

    citations = build_citations(
        bundle,
        (
            CitationRequest(
                chunk_id=item.chunk_id,
                excerpt="SYNTHETIC_RISK_CLAIM 需要人工复核",
            ),
        ),
    )

    assert citations[0].document_title == item.document_title
    assert citations[0].source_level is RiskSourceLevel.S3
    assert citations[0].source_url is None
    assert (
        citations[0].private_document_id
        == "synthetic-private-document"
    )
    assert citations[0].document_version == 2
    assert citations[0].effective_at == NOW
    assert citations[0].chunk_id == item.chunk_id
    assert citations[0].chunk_location == "人工条款 2 / 第 1 段"
    assert citations[0].excerpt == "SYNTHETIC_RISK_CLAIM 需要人工复核"


@pytest.mark.parametrize(
    "unauthorized_item",
    [
        None,
        _evidence(platform=Platform.XIAOHONGSHU),
        _evidence(workspace_id=uuid4()),
        _evidence(chunk_id=uuid4()),
    ],
)
def test_nonexistent_cross_platform_workspace_or_out_of_bundle_chunk_fails(
    unauthorized_item: EvidenceChunk | None,
) -> None:
    bundle = _bundle()
    unauthorized_chunk_id = (
        uuid4()
        if unauthorized_item is None
        else unauthorized_item.chunk_id
    )

    outcome = validate_cited_result(
        bundle,
        ProposedRiskConclusion(
            conclusion="SYNTHETIC_RISK_CLAIM",
            citations=(
                CitationRequest(
                    chunk_id=unauthorized_chunk_id,
                    excerpt="SYNTHETIC_RISK_CLAIM",
                ),
            ),
        ),
    )

    assert outcome.success is False
    assert outcome.can_persist_as_success is False
    assert outcome.citations == ()
    assert {item.code for item in outcome.diagnostics} == {
        "CITATION_CHUNK_NOT_IN_EVIDENCE_BUNDLE"
    }


def test_conclusion_outside_evidence_scope_fails_deterministically() -> None:
    bundle = _bundle()
    item = bundle.evidence[0]

    outcome = validate_cited_result(
        bundle,
        ProposedRiskConclusion(
            conclusion="UNSUPPORTED_HIGH_RISK_CONCLUSION",
            citations=(
                CitationRequest(
                    chunk_id=item.chunk_id,
                    excerpt="SYNTHETIC_RISK_CLAIM",
                ),
            ),
        ),
    )

    assert outcome.success is False
    assert outcome.can_persist_as_success is False
    assert {item.code for item in outcome.diagnostics} == {
        "CONCLUSION_EXCEEDS_EVIDENCE"
    }
    with pytest.raises(CitationValidationError):
        require_successful_validation(outcome)


def test_failed_validation_has_safe_diagnostics_without_sensitive_content() -> None:
    bundle = _bundle()

    outcome = validate_cited_result(
        bundle,
        ProposedRiskConclusion(
            conclusion="UNSUPPORTED_HIGH_RISK_CONCLUSION",
            citations=(
                CitationRequest(
                    chunk_id=uuid4(),
                    excerpt=SENSITIVE_BODY,
                ),
            ),
        ),
    )
    rendered = repr(outcome.diagnostics)

    assert SENSITIVE_BODY not in rendered
    assert "0.91" not in rendered
    assert "mock-risk-embedding" not in rendered
    assert outcome.can_persist_as_success is False


def test_bundle_rejects_forged_platform_or_workspace_evidence() -> None:
    with pytest.raises(ValueError, match="platform"):
        _bundle(_evidence(platform=Platform.XIAOHONGSHU))
    with pytest.raises(ValueError, match="workspace"):
        _bundle(_evidence(workspace_id=uuid4()))
