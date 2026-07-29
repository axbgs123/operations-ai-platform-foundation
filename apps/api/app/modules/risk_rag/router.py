from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.security import WorkspaceContext
from app.core.storage import Storage, get_storage
from app.modules.content.account_models import Platform
from app.modules.risk_rag.lifecycle import (
    InvalidLifecycleTransition,
    SourcePolicyViolation,
)
from app.modules.risk_rag.ingestion import (
    DuplicateRiskDocument,
    MAX_RISK_DOCUMENT_SIZE,
    RiskIngestionService,
)
from app.modules.risk_rag.repository import RiskDocumentRepository
from app.modules.risk_rag.schemas import (
    RiskDocumentParseInput,
    RiskDocumentCreate,
    RiskDocumentRead,
    RiskDocumentTransition,
    RiskScanRead,
    RiskFeedbackCreate,
    RiskFeedbackEventRead,
    RiskFeedbackRead,
    RiskFeedbackReview,
    RiskRuleUpdateCandidateRead,
    RiskEvaluationRead,
)
from app.modules.risk_rag.evaluation import (
    EvaluationRunVersions,
    build_ci_evaluation_payload,
)
from app.modules.risk_rag.feedback import RiskFeedbackService
from app.modules.risk_rag.models import (
    RiskDocumentStatus,
    RiskFeedbackEvent,
)
from app.modules.risk_rag.scanner import (
    IdempotencyConflict,
    RiskScanExecutionFailed,
    RiskScanInput,
    RiskScanService,
    build_default_pipeline,
)
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.permissions import (
    Permission,
    PermissionDenied,
    require_permission,
)


router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/risk-documents",
    tags=["risk-knowledge"],
)
scan_router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/risk-scans",
    tags=["risk-scans"],
)
DatabaseSession = Annotated[Session, Depends(get_session)]
ObjectStorage = Annotated[Storage, Depends(get_storage)]


def _context(
    session: Session,
    workspace_id: UUID,
    session_token: str | None,
    csrf_token: str | None,
    *,
    mutation: bool,
) -> WorkspaceContext:
    if session_token is None:
        raise HTTPException(status_code=401, detail="invalid session")
    auth = InviteAuthService(session)
    context = auth.authenticate(session_token)
    if context is None:
        raise HTTPException(status_code=401, detail="invalid session")
    if context.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="workspace not found")
    if mutation and (
        csrf_token is None
        or not auth.validate_csrf(session_token, csrf_token)
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return context


@router.post("", response_model=RiskDocumentRead, status_code=201)
def create_risk_document(
    workspace_id: UUID,
    data: RiskDocumentCreate,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> RiskDocumentRead:
    repository = RiskDocumentRepository(
        session,
        context=_context(
            session,
            workspace_id,
            session_token,
            csrf_token,
            mutation=True,
        ),
    )
    try:
        document = repository.add_private(
            platform=data.platform,
            source_level=data.source_level,
            title=data.title,
            private_document_id=data.private_document_id,
            authorization_status=data.authorization_status,
            published_at=data.published_at,
            effective_at=data.effective_at,
            accessed_at=data.accessed_at,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except SourcePolicyViolation as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return RiskDocumentRead.model_validate(document)


@router.get("/current", response_model=list[RiskDocumentRead])
def list_current_risk_documents(
    workspace_id: UUID,
    platform: Platform,
    at: Annotated[datetime, Query()],
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[RiskDocumentRead]:
    repository = RiskDocumentRepository(
        session,
        context=_context(
            session,
            workspace_id,
            session_token,
            None,
            mutation=False,
        ),
    )
    return [
        RiskDocumentRead.model_validate(document)
        for document in repository.list_current(platform=platform, at=at)
    ]


@router.get("", response_model=list[RiskDocumentRead])
def list_risk_documents(
    workspace_id: UUID,
    session: DatabaseSession,
    platform: Platform | None = None,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[RiskDocumentRead]:
    repository = RiskDocumentRepository(
        session,
        context=_context(
            session,
            workspace_id,
            session_token,
            None,
            mutation=False,
        ),
    )
    return [
        RiskDocumentRead.model_validate(document)
        for document in repository.list_visible(platform=platform)
    ]


@router.get("/{document_id}", response_model=RiskDocumentRead)
def get_risk_document(
    workspace_id: UUID,
    document_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> RiskDocumentRead:
    repository = RiskDocumentRepository(
        session,
        context=_context(
            session,
            workspace_id,
            session_token,
            None,
            mutation=False,
        ),
    )
    document = repository.get_historical(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="risk document not found")
    return RiskDocumentRead.model_validate(document)


@router.get("/{document_id}/chunks")
def list_risk_document_chunks(
    workspace_id: UUID,
    document_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[dict[str, object]]:
    repository = RiskDocumentRepository(
        session,
        context=_context(
            session,
            workspace_id,
            session_token,
            None,
            mutation=False,
        ),
    )
    document = repository.get(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="risk document not found")
    return [
        {
            "id": chunk.id,
            "document_id": chunk.document_id,
            "chunk_index": chunk.chunk_index,
            "source_location": chunk.source_location,
            "text": chunk.text,
        }
        for chunk in repository.list_chunks(document_id)
    ]


@router.get("/{document_id}/versions", response_model=list[RiskDocumentRead])
def list_risk_document_versions(
    workspace_id: UUID,
    document_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[RiskDocumentRead]:
    repository = RiskDocumentRepository(
        session,
        context=_context(
            session,
            workspace_id,
            session_token,
            None,
            mutation=False,
        ),
    )
    if repository.get(document_id) is None:
        raise HTTPException(status_code=404, detail="risk document not found")
    return [
        RiskDocumentRead.model_validate(document)
        for document in repository.version_chain(document_id)
    ]


@router.post("/{document_id}/parse", response_model=RiskDocumentRead)
def parse_risk_document(
    workspace_id: UUID,
    document_id: UUID,
    data: RiskDocumentParseInput,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> RiskDocumentRead:
    repository = RiskDocumentRepository(
        session,
        context=_context(
            session,
            workspace_id,
            session_token,
            csrf_token,
            mutation=True,
        ),
    )
    try:
        document = repository.parse_inline(
            document_id,
            text=data.text,
            source_location=data.source_location,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail="invalid risk document") from error
    if document is None:
        raise HTTPException(status_code=404, detail="risk document not found")
    session.commit()
    return RiskDocumentRead.model_validate(document)


@router.post("/{document_id}/upload", response_model=RiskDocumentRead)
async def upload_risk_document(
    workspace_id: UUID,
    document_id: UUID,
    file: Annotated[UploadFile, File()],
    redistribution_authorized: Annotated[bool, Form()],
    session: DatabaseSession,
    storage: ObjectStorage,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> RiskDocumentRead:
    context = _context(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=True,
    )
    content = await file.read(MAX_RISK_DOCUMENT_SIZE + 1)
    try:
        document = RiskIngestionService(
            session,
            context=context,
            storage=storage,
        ).ingest_file(
            document_id,
            file_name=file.filename or "risk-document.txt",
            mime_type=file.content_type or "application/octet-stream",
            content=content,
            redistribution_authorized=redistribution_authorized,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except DuplicateRiskDocument as error:
        raise HTTPException(status_code=409, detail="duplicate risk document") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return RiskDocumentRead.model_validate(document)


def _document_action(
    action: str,
    workspace_id: UUID,
    document_id: UUID,
    session: Session,
    session_token: str | None,
    csrf_token: str | None,
) -> RiskDocumentRead:
    repository = RiskDocumentRepository(
        session,
        context=_context(
            session,
            workspace_id,
            session_token,
            csrf_token,
            mutation=True,
        ),
    )
    targets = {
        "submit-review": RiskDocumentStatus.PENDING_REVIEW,
        "activate": RiskDocumentStatus.ACTIVE,
        "supersede": RiskDocumentStatus.SUPERSEDED,
        "expire": RiskDocumentStatus.EXPIRED,
        "reject": RiskDocumentStatus.REJECTED,
        "check-update": None,
    }
    if action not in targets:
        raise HTTPException(status_code=404, detail="risk document action not found")
    try:
        target = targets[action]
        if target is None:
            document = repository.get(document_id)
        else:
            document = repository.transition(document_id, target)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except InvalidLifecycleTransition as error:
        raise HTTPException(status_code=409, detail="invalid lifecycle action") from error
    if document is None:
        raise HTTPException(status_code=404, detail="risk document not found")
    session.commit()
    return RiskDocumentRead.model_validate(document)


def _document_action_endpoint(action: str):
    def endpoint(
        workspace_id: UUID,
        document_id: UUID,
        session: DatabaseSession,
        session_token: Annotated[
            str | None, Cookie(alias="session")
        ] = None,
        csrf_token: Annotated[
            str | None, Header(alias="X-CSRF-Token")
        ] = None,
    ) -> RiskDocumentRead:
        return _document_action(
            action,
            workspace_id,
            document_id,
            session,
            session_token,
            csrf_token,
        )

    return endpoint


for _action_name in (
    "submit-review",
    "activate",
    "reject",
    "supersede",
    "expire",
    "check-update",
):
    router.add_api_route(
        f"/{{document_id}}/{_action_name}",
        _document_action_endpoint(_action_name),
        methods=["POST"],
        response_model=RiskDocumentRead,
        name=f"{_action_name.replace('-', '_')}_risk_document",
    )


feedback_scan_router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/risk-scans",
    tags=["risk-feedback"],
)
feedback_router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/risk-feedback",
    tags=["risk-feedback"],
)


@feedback_scan_router.post(
    "/{scan_id}/feedback",
    response_model=RiskFeedbackRead,
    status_code=201,
)
def submit_risk_feedback(
    workspace_id: UUID,
    scan_id: UUID,
    data: RiskFeedbackCreate,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> RiskFeedbackRead:
    context = _context(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=True,
    )
    try:
        feedback = RiskFeedbackService(session, context=context).submit(
            scan_id=scan_id,
            finding_reference=data.finding_reference,
            feedback_type=data.feedback_type,
            idempotency_key=data.idempotency_key,
            comment=data.comment,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail="risk scan not found") from error
    session.commit()
    return RiskFeedbackRead.model_validate(feedback)


@feedback_router.get(
    "/candidates",
    response_model=list[RiskRuleUpdateCandidateRead],
)
def list_rule_update_candidates(
    workspace_id: UUID,
    platform: Platform,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[RiskRuleUpdateCandidateRead]:
    context = _context(
        session,
        workspace_id,
        session_token,
        None,
        mutation=False,
    )
    return [
        RiskRuleUpdateCandidateRead.model_validate(candidate)
        for candidate in RiskFeedbackService(
            session,
            context=context,
        ).rule_update_candidates(platform=platform)
    ]


@feedback_router.post(
    "/{feedback_id}/review",
    response_model=RiskFeedbackRead,
)
def review_risk_feedback(
    workspace_id: UUID,
    feedback_id: UUID,
    data: RiskFeedbackReview,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> RiskFeedbackRead:
    context = _context(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=True,
    )
    try:
        feedback = RiskFeedbackService(session, context=context).review(
            feedback_id,
            status=data.status,
            note=data.note,
            reviewed_at=datetime.now(UTC),
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail="risk feedback not found") from error
    session.commit()
    return RiskFeedbackRead.model_validate(feedback)


@feedback_router.get(
    "/{feedback_id}/events",
    response_model=list[RiskFeedbackEventRead],
)
def list_risk_feedback_events(
    workspace_id: UUID,
    feedback_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[RiskFeedbackEventRead]:
    context = _context(
        session,
        workspace_id,
        session_token,
        None,
        mutation=False,
    )
    feedback = RiskFeedbackService(session, context=context)
    try:
        item = feedback._get(feedback_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="risk feedback not found") from error
    events = session.scalars(
        select(RiskFeedbackEvent).where(
            RiskFeedbackEvent.feedback_id == item.id,
            RiskFeedbackEvent.workspace_id == workspace_id,
        ).order_by(RiskFeedbackEvent.created_at, RiskFeedbackEvent.id)
    )
    return [RiskFeedbackEventRead.model_validate(event) for event in events]


@feedback_router.get(
    "/{feedback_id}",
    response_model=RiskFeedbackRead,
)
def get_risk_feedback(
    workspace_id: UUID,
    feedback_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> RiskFeedbackRead:
    context = _context(
        session,
        workspace_id,
        session_token,
        None,
        mutation=False,
    )
    try:
        item = RiskFeedbackService(session, context=context)._get(feedback_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="risk feedback not found") from error
    return RiskFeedbackRead.model_validate(item)


@feedback_router.post(
    "/{feedback_id}/withdraw",
    response_model=RiskFeedbackRead,
)
def withdraw_risk_feedback_post(
    workspace_id: UUID,
    feedback_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> RiskFeedbackRead:
    context = _context(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=True,
    )
    try:
        feedback = RiskFeedbackService(session, context=context).withdraw(
            feedback_id,
            reason="submitter requested withdrawal",
            withdrawn_at=datetime.now(UTC),
        )
    except (PermissionDenied, PermissionError) as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail="risk feedback not found") from error
    session.commit()
    return RiskFeedbackRead.model_validate(feedback)


evaluation_router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/risk-evaluations",
    tags=["risk-evaluations"],
)


@evaluation_router.get("", response_model=RiskEvaluationRead)
def read_risk_evaluation(
    workspace_id: UUID,
    platform: Platform,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> RiskEvaluationRead:
    context = _context(
        session,
        workspace_id,
        session_token,
        None,
        mutation=False,
    )
    require_permission(context.role, Permission.MANAGE_RISK_KNOWLEDGE)
    root = Path(__file__).resolve().parents[5]
    payload = build_ci_evaluation_payload(
        root / "apps/api/tests/fixtures/risk_eval",
        versions=EvaluationRunVersions(
            rule_version="risk-rules-v1",
            prompt_version="risk-prompt-v1",
            model_version="fixed-contract-mock-v1",
            embedding_version="mock-embedding-v1",
        ),
        run_at=datetime.now(UTC),
    )
    platforms = cast(dict[str, dict[str, object]], payload["platforms"])
    item = platforms[platform.value]
    return RiskEvaluationRead(
        platform=platform,
        fixture_version=cast(str, item["fixture_version"]),
        sample_count=cast(int, item["sample_count"]),
        quality_label=cast(str, payload["quality_label"]),
        production_quality_claim_allowed=cast(
            bool,
            payload["production_quality_claim_allowed"],
        ),
        metrics=cast(dict[str, object], item["metrics"]),
        gate=cast(dict[str, object], item["gate"]),
    )


@router.post("/{document_id}/transitions", response_model=RiskDocumentRead)
def transition_risk_document(
    workspace_id: UUID,
    document_id: UUID,
    data: RiskDocumentTransition,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> RiskDocumentRead:
    repository = RiskDocumentRepository(
        session,
        context=_context(
            session,
            workspace_id,
            session_token,
            csrf_token,
            mutation=True,
        ),
    )
    try:
        document = repository.transition(document_id, data.status)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except InvalidLifecycleTransition as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if document is None:
        raise HTTPException(status_code=404, detail="risk document not found")
    session.commit()
    return RiskDocumentRead.model_validate(document)


@scan_router.post("", response_model=RiskScanRead, status_code=201)
def create_risk_scan(
    workspace_id: UUID,
    data: RiskScanInput,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> RiskScanRead:
    context = _context(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=True,
    )
    service = RiskScanService(session, context=context)
    try:
        pipeline = build_default_pipeline(
            session,
            data,
            context=context,
        )
        # Close the configuration read transaction before any Provider HTTP
        # call. Retrieval starts a new short transaction after embedding.
        session.commit()
        scan = service.execute(
            data,
            pipeline=pipeline,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except IdempotencyConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except RiskScanExecutionFailed as error:
        session.commit()
        raise HTTPException(
            status_code=422,
            detail={
                "code": "RISK_SCAN_VALIDATION_FAILED",
                "scan_id": str(error.scan_id),
            },
        ) from error
    session.commit()
    return RiskScanRead.model_validate(scan)


@scan_router.get("/{scan_id}", response_model=RiskScanRead)
def get_risk_scan(
    workspace_id: UUID,
    scan_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> RiskScanRead:
    context = _context(
        session,
        workspace_id,
        session_token,
        None,
        mutation=False,
    )
    try:
        scan = RiskScanService(session, context=context).get(scan_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return RiskScanRead.model_validate(scan)


@scan_router.get("", response_model=list[RiskScanRead])
def list_risk_scans(
    workspace_id: UUID,
    content_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[RiskScanRead]:
    context = _context(
        session,
        workspace_id,
        session_token,
        None,
        mutation=False,
    )
    return [
        RiskScanRead.model_validate(scan)
        for scan in RiskScanService(
            session,
            context=context,
        ).history(content_id)
    ]
