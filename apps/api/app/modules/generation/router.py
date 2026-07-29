from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import get_session
from app.modules.generation.cover_models import CoverRequest
from app.modules.generation.cover_service import (
    CoverGenerationCoordinator,
    CoverIdempotencyConflict,
)
from app.modules.generation.context import GenerationContextBuilder
from app.modules.generation.models import (
    CoverArtifactAttempt,
    CoverGenerationRun,
    TextGenerationRun,
)
from app.modules.generation.schemas import GenerationContext, GenerationInputs
from app.modules.generation.tasks import (
    get_cover_generation_enqueuer,
    get_text_generation_enqueuer,
)
from app.modules.generation.text_service import (
    GeneratedTextResult,
    cancel_text_generation,
    create_text_generation,
    edit_text_generation,
    retry_text_generation,
)
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.permissions import (
    Permission,
    PermissionDenied,
    require_permission,
)


router = APIRouter(tags=["generation"])
DatabaseSession = Annotated[Session, Depends(get_session)]


class TextGenerationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    account_id: UUID
    model_config_id: UUID
    context: GenerationContext
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    original_result: GeneratedTextResult | None
    final_title: str | None
    final_copy: str | None
    adoption_status: Literal["pending", "adopted", "rejected", "discarded"]
    modification_magnitude: float
    modification_algorithm_version: str
    retry_of_run_id: UUID | None
    error_code: str | None
    status_detail: str | None
    created_at: datetime
    completed_at: datetime | None


class TextGenerationEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final_title: str = Field(min_length=1, max_length=2_000)
    final_copy: str = Field(min_length=1, max_length=100_000)
    adoption_status: Literal["pending", "adopted", "rejected", "discarded"]


class CoverGenerationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_id: UUID
    request: CoverRequest


class CoverAttemptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    attempt_number: int
    status: str
    output_sha256: str | None
    output_mime_type: str | None
    output_width: int | None
    output_height: int | None
    layout_version: str | None
    ocr_model_version: str | None
    ocr_confidence: float | None
    risk_scan_id: UUID | None
    risk_rule_version: str | None
    requires_human_review: bool
    publish_eligible: bool
    disclaimer: str
    error_code: str | None


class CoverGenerationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    content_id: UUID
    platform: str
    provider: str
    model_id: str
    cover_mode: str
    status: str
    attempt_count: int
    error_code: str | None
    status_detail: str | None
    completed_at: datetime | None
    latest_attempt: CoverAttemptRead | None


def _context(
    session: Session,
    session_token: str | None,
    csrf_token: str | None,
    *,
    workspace_id: UUID,
    mutation: bool,
):
    if session_token is None:
        raise HTTPException(status_code=401, detail="invalid session")
    auth = InviteAuthService(session)
    context = auth.authenticate(session_token)
    if context is None:
        raise HTTPException(status_code=401, detail="invalid session")
    if context.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="workspace not found")
    if mutation and (
        csrf_token is None or not auth.validate_csrf(session_token, csrf_token)
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    try:
        require_permission(
            context.role,
            Permission.WRITE_CONTENT if mutation else Permission.READ_CONTENT,
        )
    except PermissionDenied as error:
        raise HTTPException(
            status_code=403,
            detail="permission denied",
        ) from error
    return context


def _read_run(
    session: Session,
    workspace_id: UUID,
    run_id: UUID,
) -> TextGenerationRun:
    run = session.scalar(
        select(TextGenerationRun).where(
            TextGenerationRun.id == run_id,
            TextGenerationRun.workspace_id == workspace_id,
        )
    )
    if run is None:
        raise HTTPException(
            status_code=404,
            detail="text generation run not found",
        )
    return run


def _read_cover_run(
    session: Session,
    workspace_id: UUID,
    run_id: UUID,
) -> CoverGenerationRun:
    run = session.scalar(
        select(CoverGenerationRun).where(
            CoverGenerationRun.id == run_id,
            CoverGenerationRun.workspace_id == workspace_id,
        )
    )
    if run is None:
        raise HTTPException(
            status_code=404,
            detail="cover generation run not found",
        )
    return run


def _cover_payload(
    session: Session,
    run: CoverGenerationRun,
) -> CoverGenerationRunRead:
    attempt = session.scalar(
        select(CoverArtifactAttempt)
        .where(
            CoverArtifactAttempt.run_id == run.id,
            CoverArtifactAttempt.workspace_id == run.workspace_id,
        )
        .order_by(CoverArtifactAttempt.attempt_number.desc())
    )
    return CoverGenerationRunRead(
        id=run.id,
        workspace_id=run.workspace_id,
        content_id=run.content_id,
        platform=run.platform,
        provider=run.provider,
        model_id=run.model_id,
        cover_mode=run.cover_mode,
        status=run.status.value,
        attempt_count=run.attempt_count,
        error_code=run.error_code,
        status_detail=run.status_detail,
        completed_at=run.completed_at,
        latest_attempt=(
            CoverAttemptRead.model_validate(attempt)
            if attempt is not None
            else None
        ),
    )


@router.post(
    "/v1/workspaces/{workspace_id}/generation/cover-runs",
    response_model=CoverGenerationRunRead,
    status_code=202,
)
def request_cover_generation(
    workspace_id: UUID,
    data: CoverGenerationCreate,
    background_tasks: BackgroundTasks,
    session: DatabaseSession,
    enqueuer: Annotated[
        Callable[[UUID], None],
        Depends(get_cover_generation_enqueuer),
    ],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> CoverGenerationRunRead:
    context = _context(
        session,
        session_token,
        csrf_token,
        workspace_id=workspace_id,
        mutation=True,
    )
    factory = sessionmaker(
        bind=session.get_bind(),
        expire_on_commit=False,
    )
    try:
        run_id = CoverGenerationCoordinator(
            factory,
            context=context,
        ).request(
            content_id=data.content_id,
            request=data.request,
            idempotency_key=idempotency_key,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except CoverIdempotencyConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    run = _read_cover_run(session, workspace_id, run_id)
    background_tasks.add_task(enqueuer, run.id)
    return _cover_payload(session, run)


@router.get(
    "/v1/workspaces/{workspace_id}/generation/cover-runs/{run_id}",
    response_model=CoverGenerationRunRead,
)
def read_cover_generation(
    workspace_id: UUID,
    run_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> CoverGenerationRunRead:
    _context(
        session,
        session_token,
        None,
        workspace_id=workspace_id,
        mutation=False,
    )
    return _cover_payload(
        session,
        _read_cover_run(session, workspace_id, run_id),
    )


@router.post(
    "/v1/workspaces/{workspace_id}/generation/text-runs",
    response_model=TextGenerationRunRead,
    status_code=202,
)
def request_text_generation(
    workspace_id: UUID,
    data: GenerationInputs,
    background_tasks: BackgroundTasks,
    session: DatabaseSession,
    enqueuer: Annotated[
        Callable[[UUID], None],
        Depends(get_text_generation_enqueuer),
    ],
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
):
    try:
        context = _context(
            session,
            session_token,
            csrf_token,
            workspace_id=workspace_id,
            mutation=True,
        )
        domain_run = GenerationContextBuilder(session, context).create_run(data)
        run, should_enqueue = create_text_generation(
            session,
            domain_run.context,
            requested_by=context.member_id,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    if should_enqueue:
        background_tasks.add_task(enqueuer, run.id)
    return run


@router.get(
    "/v1/workspaces/{workspace_id}/generation/text-runs/{run_id}",
    response_model=TextGenerationRunRead,
)
def read_text_generation(
    workspace_id: UUID,
    run_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
):
    try:
        _context(
            session,
            session_token,
            None,
            workspace_id=workspace_id,
            mutation=False,
        )
        return _read_run(session, workspace_id, run_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post(
    "/v1/workspaces/{workspace_id}/generation/text-runs/{run_id}/cancel",
    response_model=TextGenerationRunRead,
)
def cancel_generation(
    workspace_id: UUID,
    run_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
):
    _context(
        session,
        session_token,
        csrf_token,
        workspace_id=workspace_id,
        mutation=True,
    )
    _read_run(session, workspace_id, run_id)
    run = cancel_text_generation(session, run_id)
    session.commit()
    return run


@router.post(
    "/v1/workspaces/{workspace_id}/generation/text-runs/{run_id}/retry",
    response_model=TextGenerationRunRead,
    status_code=202,
)
def retry_generation(
    workspace_id: UUID,
    run_id: UUID,
    background_tasks: BackgroundTasks,
    session: DatabaseSession,
    enqueuer: Annotated[
        Callable[[UUID], None],
        Depends(get_text_generation_enqueuer),
    ],
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
):
    _context(
        session,
        session_token,
        csrf_token,
        workspace_id=workspace_id,
        mutation=True,
    )
    _read_run(session, workspace_id, run_id)
    try:
        run = retry_text_generation(session, run_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    session.commit()
    background_tasks.add_task(enqueuer, run.id)
    return run


@router.patch(
    "/v1/workspaces/{workspace_id}/generation/text-runs/{run_id}",
    response_model=TextGenerationRunRead,
)
def edit_generation(
    workspace_id: UUID,
    run_id: UUID,
    data: TextGenerationEdit,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
):
    _context(
        session,
        session_token,
        csrf_token,
        workspace_id=workspace_id,
        mutation=True,
    )
    _read_run(session, workspace_id, run_id)
    try:
        run = edit_text_generation(
            session,
            run_id,
            final_title=data.final_title,
            final_copy=data.final_copy,
            adoption_status=data.adoption_status,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    session.commit()
    return run
