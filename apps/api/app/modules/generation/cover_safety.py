import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID

from PIL import Image
from app.core.security import WorkspaceContext
from app.modules.content.account_models import Platform
from app.modules.generation.cover_service import CoverSafetyResult, SessionFactory
from app.modules.imports.ocr_adapters import VisionAdapter
from app.modules.risk_rag.models import RiskScanNode
from app.modules.risk_rag.scanner import (
    OcrRegion,
    OcrResult,
    OcrStatus,
    RiskScanInput,
    RiskScanOutput,
    RiskScanService,
    RiskScanVersions,
    ScanSeverity,
    build_default_pipeline,
)


class PersistedCoverSafetyGate:
    """Fail-closed OCR/RiskRAG bridge for generated cover artifacts."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        context: WorkspaceContext,
        account_id: UUID,
        title: str,
        body: str,
        vision_adapter: VisionAdapter | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._context = context
        self._account_id = account_id
        self._title = title
        self._body = body
        self._vision_adapter = vision_adapter
        self._now = now

    def scan(
        self,
        *,
        png_bytes: bytes,
        workspace_id: UUID,
        platform: str,
        content_id: UUID,
    ) -> CoverSafetyResult:
        if workspace_id != self._context.workspace_id:
            raise LookupError("workspace not found")
        image = Image.open(BytesIO(png_bytes))
        image.verify()
        requested_at = self._now()
        if requested_at.tzinfo is None:
            raise ValueError("cover safety clock must be timezone-aware")
        ocr = OcrResult(
            status=OcrStatus.UNAVAILABLE,
            regions=(),
            confidence_source="cover-ocr-unavailable-v1",
            requires_human_review=True,
        )
        ocr_provider = "unavailable"
        ocr_model_id = "cover-ocr-unavailable-v1"
        ocr_contract_version = "cover-ocr-unavailable-v1"
        if self._vision_adapter is not None:
            try:
                recognized = self._vision_adapter.recognize(
                    png_bytes,
                    "image/png",
                )
            except Exception:
                ocr = OcrResult(
                    status=OcrStatus.FAILED,
                    regions=(),
                    confidence_source="cover-ocr-failed-v1",
                    requires_human_review=True,
                )
            else:
                regions = tuple(
                    OcrRegion(
                        text=region.text,
                        bbox=(
                            region.region.x,
                            region.region.y,
                            region.region.width,
                            region.region.height,
                        ),
                        confidence=0,
                    )
                    for region in recognized.text_regions
                )
                ocr = OcrResult(
                    status=(
                        OcrStatus.SUCCEEDED if regions else OcrStatus.EMPTY
                    ),
                    regions=regions,
                    confidence_source=recognized.confidence_source,
                    requires_human_review=True,
                )
                ocr_provider = (
                    "qianwen"
                    if recognized.model_id.startswith("qwen")
                    else "mock"
                )
                ocr_model_id = recognized.model_id
                ocr_contract_version = recognized.contract_version
        scan_input = RiskScanInput(
            workspace_id=workspace_id,
            account_id=self._account_id,
            content_id=content_id,
            platform=Platform(platform),
            node=RiskScanNode.AFTER_GENERATION,
            title=self._title,
            body=self._body,
            ocr=ocr,
            idempotency_key=(
                "cover:"
                + hashlib.sha256(png_bytes).hexdigest()
            ),
            versions=RiskScanVersions(
                rule_version="cover-risk-rules-v1",
                evidence_version="active-at-scan-time",
                embedding_model_id="mock-risk-embedding",
                embedding_version="mock-risk-embedding-v1",
                embedding_dimension=3,
                rag_model_version="deterministic-no-rag-v1",
                scanner_version="generated-cover-scanner-v1",
                ocr_provider=ocr_provider,
                ocr_model_id=ocr_model_id,
                ocr_contract_version=ocr_contract_version,
                ocr_config_version="fail-closed-v1",
            ),
            requested_at=requested_at,
        )
        with self._session_factory() as session, session.begin():
            scan = RiskScanService(
                session,
                context=self._context,
            ).execute(
                scan_input,
                pipeline=build_default_pipeline(session, scan_input),
            )
            output = RiskScanOutput.model_validate(scan.result)
            scan_id = scan.id
        return CoverSafetyResult(
            ocr_model_version=ocr_model_id,
            ocr_confidence=0,
            risk_scan_id=scan_id,
            risk_rule_version=output.versions.rule_version,
            high_risk=any(
                finding.severity is ScanSeverity.HIGH
                for finding in output.findings
            ),
            requires_human_review=True,
        )
