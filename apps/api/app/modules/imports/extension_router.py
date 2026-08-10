from collections import defaultdict, deque
from datetime import UTC, datetime
import logging
import time
from typing import Annotated, cast
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Request,
    status,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.config import get_settings
from app.core.logging import current_request_id, emit_log
from app.core.security import WorkspaceContext, WorkspaceRole
from app.core.storage import Storage, get_storage
from app.modules.content.account_models import Platform
from app.modules.content.account_models import PlatformAccount
from app.modules.imports.capture_models import CaptureTask
from app.modules.imports.capture_models import CaptureTaskStatus
from app.modules.imports.capture_service import (
    IdempotencyConflict,
    clear_task_object,
    create_task,
    get_capture_enqueuer,
    task_payload,
    transition_task,
)
from app.modules.imports.vision_binding import resolve_vision_binding
from app.modules.models.config_service import SecretCipher
from app.modules.models.models import ModelConfig, ModelConfigStatus
from app.modules.imports.service import ImportService
from app.modules.metrics.models import ContentType
from app.modules.imports.extension_auth import (
    AuthenticatedExtension,
    ExtensionTokenService,
    IssuedExtensionToken,
)
from app.modules.imports.extension_pairing import (
    ExtensionPairingService,
    PairingCodeRateLimited,
    PairingCodeUnavailable,
)
from app.modules.imports.models import ExtensionToken, ExtensionTokenScope
from app.modules.workspace.auth import (
    InvalidInviteCode,
    InviteAuthService,
    InviteRateLimitExceeded,
)
from app.modules.workspace.permissions import (
    Permission,
    PermissionDenied,
    require_permission,
)
from app.modules.workspace.models import Workspace, WorkspaceMember


router = APIRouter(prefix="/v1/extension", tags=["extension-auth"])
review_router = APIRouter(tags=["extension-capture-review"])
DatabaseSession = Annotated[Session, Depends(get_session)]
ObjectStorage = Annotated[Storage, Depends(get_storage)]
binding_attempts: dict[str, deque[datetime]] = defaultdict(deque)
pairing_attempts: dict[str, deque[datetime]] = defaultdict(deque)
CAPTURE_EXTENSION_CLIENT = "operations-capture-extension"
_pairing_logger = logging.getLogger("operations_ai.imports.extension_pairing")


class ExtensionBindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invite_code: str = Field(min_length=20, max_length=500)
    client_id: str = Field(min_length=3, max_length=120)


class ExtensionBindResponse(BaseModel):
    access_token: str
    token_type: str
    workspace_id: UUID
    member_id: UUID
    client_id: str
    scopes: list[str]
    issued_at: datetime
    expires_at: datetime
    provider_mode: str
    region: str | None
    workspace_name: str
    member_display_name: str
    web_origin: str


class ExtensionBindingRead(BaseModel):
    workspace_id: UUID
    member_id: UUID
    client_id: str
    scopes: list[str]
    expires_at: datetime
    provider_mode: str
    region: str | None
    workspace_name: str
    member_display_name: str
    web_origin: str


class ExtensionPairingCodeRead(BaseModel):
    pairing_code: str
    expires_at: datetime
    workspace_id: UUID
    workspace_name: str


class ExtensionPairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pairing_code: str = Field(min_length=1, max_length=64)
    client_id: str = Field(min_length=3, max_length=120)


def _emit_pairing_event(
    *,
    event: str,
    message_code: str,
    started_at: float,
    workspace_id: UUID | None = None,
    member_id: UUID | None = None,
    client_id: str | None = None,
    error_code: str | None = None,
) -> None:
    emit_log(
        _pairing_logger,
        event=event,
        message_code=message_code,
        request_id=current_request_id(),
        workspace_id=workspace_id,
        member_id=member_id,
        client_id=client_id,
        error_code=error_code,
        duration_ms=round((time.monotonic() - started_at) * 1000, 3),
    )


def _binding_metadata(
    session: Session,
    *,
    workspace_id: UUID,
    member_id: UUID,
) -> tuple[str, str]:
    workspace = session.get(Workspace, workspace_id)
    member = session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.id == member_id,
            WorkspaceMember.workspace_id == workspace_id,
        )
    )
    if workspace is None or member is None:
        raise HTTPException(status_code=401, detail="invalid extension token")
    return workspace.name, member.display_name


def _binding_response(
    session: Session,
    issued: IssuedExtensionToken,
) -> ExtensionBindResponse:
    provider_mode, region = _vision_disclosure(session, issued.workspace_id)
    workspace_name, member_display_name = _binding_metadata(
        session,
        workspace_id=issued.workspace_id,
        member_id=issued.member_id,
    )
    return ExtensionBindResponse(
        access_token=issued.access_token,
        token_type="Bearer",
        workspace_id=issued.workspace_id,
        member_id=issued.member_id,
        client_id=issued.client_id,
        scopes=list(issued.scopes),
        issued_at=issued.issued_at,
        expires_at=issued.expires_at,
        provider_mode=provider_mode,
        region=region,
        workspace_name=workspace_name,
        member_display_name=member_display_name,
        web_origin=get_settings().web_origin,
    )


def _binding_read(
    session: Session,
    authenticated: AuthenticatedExtension,
) -> ExtensionBindingRead:
    provider_mode, region = _vision_disclosure(session, authenticated.workspace_id)
    workspace_name, member_display_name = _binding_metadata(
        session,
        workspace_id=authenticated.workspace_id,
        member_id=authenticated.member_id,
    )
    return ExtensionBindingRead(
        workspace_id=authenticated.workspace_id,
        member_id=authenticated.member_id,
        client_id=authenticated.client_id,
        scopes=list(authenticated.scopes),
        expires_at=authenticated.expires_at,
        provider_mode=provider_mode,
        region=region,
        workspace_name=workspace_name,
        member_display_name=member_display_name,
        web_origin=get_settings().web_origin,
    )


def _vision_disclosure(session: Session, workspace_id: UUID) -> tuple[str, str | None]:
    if get_settings().app_mock_mode:
        return "mock", None
    configs = session.scalars(
        select(ModelConfig).where(
            ModelConfig.workspace_id == workspace_id,
            ModelConfig.status != ModelConfigStatus.INCOMPATIBLE,
        )
    )
    config = next(
        (
            item
            for item in configs
            if item.provider == "qianwen" and "vision" in item.capabilities
        ),
        None,
    )
    return ("qianwen", config.region) if config is not None else ("unavailable", None)


def _bearer(
    session: Session,
    authorization: str | None,
    *,
    required_scope: ExtensionTokenScope | None = None,
    workspace_id: UUID | None = None,
) -> AuthenticatedExtension:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="invalid extension token")
    token = authorization.removeprefix("Bearer ").strip()
    authenticated = ExtensionTokenService(session).authenticate(token)
    if authenticated is None:
        raise HTTPException(status_code=401, detail="invalid extension token")
    if workspace_id is not None and authenticated.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="extension resource not found")
    if required_scope is not None and required_scope.value not in authenticated.scopes:
        raise HTTPException(status_code=403, detail="extension scope denied")
    return authenticated


@router.post(
    "/bind",
    response_model=ExtensionBindResponse,
    status_code=201,
    deprecated=True,
)
def bind_extension(
    data: ExtensionBindRequest,
    request: Request,
    session: DatabaseSession,
    extension_client: Annotated[str | None, Header(alias="X-Extension-Client")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ExtensionBindResponse:
    if extension_client is None or extension_client != data.client_id:
        raise HTTPException(status_code=422, detail="invalid extension client")
    key = idempotency_key or f"{data.client_id}:{data.invite_code}"
    fingerprint = ExtensionTokenService._digest(key)
    if session.scalar(
        select(ExtensionToken.id).where(
            ExtensionToken.exchange_fingerprint == fingerprint
        )
    ):
        raise HTTPException(status_code=409, detail="binding already exchanged")
    service = ExtensionTokenService(session, attempts=binding_attempts)
    try:
        issued = service.bind(
            data.invite_code,
            client_id=data.client_id,
            display_name="扩展成员",
            client_key=request.client.host if request.client else "unknown",
        )
        record = session.get(ExtensionToken, issued.token_id)
        assert record is not None
        record.exchange_fingerprint = fingerprint
        session.commit()
    except InvalidInviteCode as error:
        raise HTTPException(status_code=401, detail="invalid invite code") from error
    except InviteRateLimitExceeded as error:
        raise HTTPException(status_code=429, detail="too many attempts") from error
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="binding already exchanged"
        ) from error
    return _binding_response(session, issued)


@router.post("/pair", response_model=ExtensionBindResponse, status_code=201)
def pair_extension(
    data: ExtensionPairRequest,
    session: DatabaseSession,
    extension_client: Annotated[str | None, Header(alias="X-Extension-Client")] = None,
) -> ExtensionBindResponse:
    started_at = time.monotonic()
    if (
        extension_client != CAPTURE_EXTENSION_CLIENT
        or data.client_id != CAPTURE_EXTENSION_CLIENT
    ):
        _emit_pairing_event(
            event="extension.pairing.invalid",
            message_code="EXTENSION_PAIR_INVALID",
            started_at=started_at,
            error_code="EXTENSION_PAIR_INVALID",
        )
        raise HTTPException(
            status_code=401,
            detail="pairing code invalid or expired",
        )
    try:
        issued = ExtensionPairingService(
            session,
            attempts=pairing_attempts,
        ).redeem(data.pairing_code, client_id=data.client_id)
        session.commit()
    except PairingCodeUnavailable as error:
        session.rollback()
        _emit_pairing_event(
            event="extension.pairing.invalid",
            message_code="EXTENSION_PAIR_INVALID",
            started_at=started_at,
            error_code="EXTENSION_PAIR_INVALID",
        )
        raise HTTPException(
            status_code=401,
            detail="pairing code invalid or expired",
        ) from error
    except PairingCodeRateLimited as error:
        session.rollback()
        _emit_pairing_event(
            event="extension.pairing.rate_limited",
            message_code="EXTENSION_PAIR_RATE_LIMITED",
            started_at=started_at,
            error_code="EXTENSION_PAIR_RATE_LIMITED",
        )
        raise HTTPException(status_code=429, detail="too many attempts") from error
    except Exception as error:
        session.rollback()
        _emit_pairing_event(
            event="extension.pairing.internal_failure",
            message_code="EXTENSION_PAIR_INTERNAL_FAILURE",
            started_at=started_at,
            error_code="EXTENSION_PAIR_INTERNAL_FAILURE",
        )
        raise HTTPException(status_code=500, detail="pairing unavailable") from error
    _emit_pairing_event(
        event="extension.pairing.succeeded",
        message_code="EXTENSION_PAIR_SUCCEEDED",
        started_at=started_at,
        workspace_id=issued.workspace_id,
        member_id=issued.member_id,
        client_id=CAPTURE_EXTENSION_CLIENT,
    )
    return _binding_response(session, issued)


@router.get("/binding", response_model=ExtensionBindingRead)
def read_extension_binding(
    session: DatabaseSession,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> ExtensionBindingRead:
    authenticated = _bearer(
        session,
        authorization,
        required_scope=ExtensionTokenScope.CAPTURE_READ,
    )
    return _binding_read(session, authenticated)


@router.get(
    "/workspaces/{workspace_id}/binding",
    response_model=ExtensionBindingRead,
)
def read_scoped_extension_binding(
    workspace_id: UUID,
    session: DatabaseSession,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> ExtensionBindingRead:
    authenticated = _bearer(
        session,
        authorization,
        required_scope=ExtensionTokenScope.CAPTURE_READ,
        workspace_id=workspace_id,
    )
    return _binding_read(session, authenticated)


@router.delete("/binding", status_code=status.HTTP_204_NO_CONTENT)
def revoke_extension_binding(
    session: DatabaseSession,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> None:
    authenticated = _bearer(session, authorization)
    ExtensionTokenService(session).revoke(authenticated.token_id)
    session.commit()


def _pairing_context(
    session: Session,
    *,
    workspace_id: UUID,
    session_token: str | None,
    csrf_token: str | None,
) -> WorkspaceContext:
    if session_token is None:
        raise HTTPException(status_code=401, detail="invalid session")
    auth = InviteAuthService(session)
    context = auth.authenticate(session_token)
    if context is None:
        raise HTTPException(status_code=401, detail="invalid session")
    if context.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="workspace not found")
    if csrf_token is None or not auth.validate_csrf(session_token, csrf_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    try:
        require_permission(context.role, Permission.WRITE_CONTENT)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    return context


@review_router.post(
    "/v1/workspaces/{workspace_id}/extension-pairing-codes",
    response_model=ExtensionPairingCodeRead,
    status_code=201,
    tags=["extension-auth"],
)
def create_extension_pairing_code(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> ExtensionPairingCodeRead:
    started_at = time.monotonic()
    context = _pairing_context(
        session,
        workspace_id=workspace_id,
        session_token=session_token,
        csrf_token=csrf_token,
    )
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    if context.member_id is None:
        raise HTTPException(status_code=401, detail="invalid session")
    try:
        created = ExtensionPairingService(session).create(
            workspace_id=context.workspace_id,
            member_id=context.member_id,
        )
        session.commit()
    except PairingCodeUnavailable as error:
        session.rollback()
        _emit_pairing_event(
            event="extension.pairing_code.unavailable",
            message_code="EXTENSION_PAIRING_CODE_UNAVAILABLE",
            started_at=started_at,
            workspace_id=workspace_id,
            member_id=context.member_id,
            error_code="EXTENSION_PAIRING_CODE_UNAVAILABLE",
        )
        raise HTTPException(status_code=404, detail="workspace not found") from error
    except Exception as error:
        session.rollback()
        _emit_pairing_event(
            event="extension.pairing_code.internal_failure",
            message_code="EXTENSION_PAIR_INTERNAL_FAILURE",
            started_at=started_at,
            workspace_id=workspace_id,
            member_id=context.member_id,
            error_code="EXTENSION_PAIR_INTERNAL_FAILURE",
        )
        raise HTTPException(status_code=500, detail="pairing unavailable") from error
    _emit_pairing_event(
        event="extension.pairing_code.created",
        message_code="EXTENSION_PAIRING_CODE_CREATED",
        started_at=started_at,
        workspace_id=workspace.id,
        member_id=context.member_id,
    )
    return ExtensionPairingCodeRead(
        pairing_code=created.code,
        expires_at=created.expires_at,
        workspace_id=workspace.id,
        workspace_name=workspace.name,
    )


class ExtensionCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Platform
    page_version: str = Field(min_length=1, max_length=80)
    page_identifier: str = Field(min_length=1, max_length=160)
    collected_at: datetime
    screenshot_data_url: str = Field(min_length=20, max_length=14_000_000)


class ExtensionCaptureTaskRead(BaseModel):
    task_id: UUID
    workspace_id: UUID
    platform: Platform
    page_version: str
    status: CaptureTaskStatus
    request_id: str
    review_url: str
    expires_at: datetime
    recognition: dict[str, object] | None
    error: str | None
    formal_snapshot_ids: list[str]
    provider_mode: str
    region: str | None


@router.post(
    "/workspaces/{workspace_id}/capture-tasks",
    response_model=ExtensionCaptureTaskRead,
    status_code=202,
)
def create_extension_capture_task(
    workspace_id: UUID,
    data: ExtensionCaptureRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: DatabaseSession,
    storage: ObjectStorage,
    enqueuer=Depends(get_capture_enqueuer),
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key required")
    authenticated = _bearer(
        session,
        authorization,
        required_scope=ExtensionTokenScope.CAPTURE_CREATE,
        workspace_id=workspace_id,
    )
    if ExtensionTokenScope.CAPTURE_UPLOAD.value not in authenticated.scopes:
        raise HTTPException(status_code=403, detail="extension scope denied")
    member = session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.id == authenticated.member_id,
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.revoked_at.is_(None),
        )
    )
    if member is None:
        raise HTTPException(status_code=404, detail="extension resource not found")
    settings = get_settings()
    try:
        binding = resolve_vision_binding(
            session,
            WorkspaceContext(
                workspace_id=workspace_id,
                member_id=member.id,
                role=cast(WorkspaceRole, member.role.value),
            ),
            platform=data.platform,
            content_type=ContentType.VIDEO,
            cipher=SecretCipher(
                settings.model_secret_encryption_key.get_secret_value()
            ),
            mock_mode=settings.app_mock_mode,
        )
    except LookupError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "MODEL_CONFIGURATION_REQUIRED",
                "message": "请联系管理员配置支持 vision 的模型",
            },
        ) from error
    try:
        task = create_task(
            session,
            workspace_id=workspace_id,
            token_id=authenticated.token_id,
            member_id=authenticated.member_id,
            platform=data.platform,
            page_version=data.page_version,
            page_identifier=data.page_identifier,
            collected_at=data.collected_at,
            idempotency_key=idempotency_key,
            screenshot_data_url=data.screenshot_data_url,
            binding=binding,
            storage=storage if binding.provider != "mock" else None,
        )
    except IdempotencyConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    if binding.provider != "mock":
        background_tasks.add_task(enqueuer, task.id)
    return task_payload(
        task, request_id=request.headers.get("X-Request-ID", str(task.id))
    )


@router.get(
    "/capture-tasks/{task_id}",
    response_model=ExtensionCaptureTaskRead,
    status_code=200,
)
def read_extension_capture_task(
    task_id: UUID,
    request: Request,
    session: DatabaseSession,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> dict[str, object]:
    authenticated = _bearer(
        session,
        authorization,
        required_scope=ExtensionTokenScope.CAPTURE_READ,
    )
    task = session.scalar(
        select(CaptureTask).where(
            CaptureTask.id == task_id,
            CaptureTask.workspace_id == authenticated.workspace_id,
            CaptureTask.token_id == authenticated.token_id,
        )
    )
    if task is None:
        raise HTTPException(status_code=404, detail="capture task not found")
    return task_payload(
        task, request_id=request.headers.get("X-Request-ID", str(task.id))
    )


@router.get(
    "/workspaces/{workspace_id}/capture-tasks/{task_id}",
    response_model=ExtensionCaptureTaskRead,
    status_code=200,
)
def read_scoped_extension_capture_task(
    workspace_id: UUID,
    task_id: UUID,
    request: Request,
    session: DatabaseSession,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> dict[str, object]:
    authenticated = _bearer(
        session,
        authorization,
        required_scope=ExtensionTokenScope.CAPTURE_READ,
        workspace_id=workspace_id,
    )
    task = session.scalar(
        select(CaptureTask).where(
            CaptureTask.id == task_id,
            CaptureTask.workspace_id == workspace_id,
            CaptureTask.token_id == authenticated.token_id,
        )
    )
    if task is None:
        raise HTTPException(status_code=404, detail="capture task not found")
    return task_payload(
        task, request_id=request.headers.get("X-Request-ID", str(task.id))
    )


@router.post(
    "/capture-tasks/{task_id}/cancel",
    response_model=ExtensionCaptureTaskRead,
    status_code=200,
)
def cancel_extension_capture_task(
    task_id: UUID,
    request: Request,
    session: DatabaseSession,
    storage: ObjectStorage,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> dict[str, object]:
    authenticated = _bearer(
        session,
        authorization,
        required_scope=ExtensionTokenScope.CAPTURE_READ,
    )
    task = session.scalar(
        select(CaptureTask).where(
            CaptureTask.id == task_id,
            CaptureTask.workspace_id == authenticated.workspace_id,
            CaptureTask.token_id == authenticated.token_id,
        )
    )
    if task is None:
        raise HTTPException(status_code=404, detail="capture task not found")
    try:
        transition_task(task, CaptureTaskStatus.CANCELLED)
    except ValueError as error:
        raise HTTPException(
            status_code=409, detail="capture task cannot be cancelled"
        ) from error
    clear_task_object(
        task,
        storage=storage if task.provider != "mock" else None,
    )
    session.commit()
    return task_payload(
        task, request_id=request.headers.get("X-Request-ID", str(task.id))
    )


@router.post("/capture-tasks/{task_id}/confirm", status_code=403)
def extension_cannot_confirm_capture_task() -> None:
    raise HTTPException(status_code=403, detail="web review confirmation required")


class WebCaptureConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    corrections: dict[str, str] = Field(default_factory=dict)


@review_router.get(
    "/v1/imports/capture-tasks/{task_id}",
    response_model=ExtensionCaptureTaskRead,
)
def read_capture_task_in_web(
    task_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> dict[str, object]:
    if session_token is None:
        raise HTTPException(status_code=401, detail="invalid session")
    context = InviteAuthService(session).authenticate(session_token)
    if context is None:
        raise HTTPException(status_code=401, detail="invalid session")
    task = session.get(CaptureTask, task_id)
    if task is None or task.workspace_id != context.workspace_id:
        raise HTTPException(status_code=404, detail="capture task not found")
    return task_payload(task, request_id=str(task.id))


@review_router.post(
    "/v1/imports/capture-tasks/{task_id}/confirm",
    response_model=ExtensionCaptureTaskRead,
    status_code=200,
)
def confirm_capture_task_in_web(
    task_id: UUID,
    data: WebCaptureConfirmation,
    session: DatabaseSession,
    storage: ObjectStorage,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict[str, object]:
    if session_token is None:
        raise HTTPException(status_code=401, detail="invalid session")
    auth = InviteAuthService(session)
    context = auth.authenticate(session_token)
    if context is None:
        raise HTTPException(status_code=401, detail="invalid session")
    if csrf_token is None or not auth.validate_csrf(session_token, csrf_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    task = session.get(CaptureTask, task_id)
    if task is None or task.workspace_id != context.workspace_id:
        raise HTTPException(status_code=404, detail="capture task not found")
    try:
        require_permission(context.role, Permission.WRITE_CONTENT)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    if task.status != CaptureTaskStatus.SUCCEEDED:
        raise HTTPException(status_code=409, detail="capture task is not ready")
    if task.confirmed_at is not None:
        return task_payload(task, request_id=str(task.id))
    # Reuse the existing import confirmation path for the explicitly selected account.
    account = session.scalar(
        select(PlatformAccount).where(
            PlatformAccount.id == data.account_id,
            PlatformAccount.workspace_id == task.workspace_id,
            PlatformAccount.platform == task.platform,
        )
    )
    if account is None:
        raise HTTPException(status_code=404, detail="account not found")
    if task.recognition_output:
        candidates = cast(
            list[dict[str, object]],
            task.recognition_output.get("metric_candidates", []),
        )
        metrics = {
            str(item["key"]): data.corrections.get(str(item["key"]), str(item["value"]))
            for item in candidates
            if isinstance(item, dict) and "key" in item and "value" in item
        }
        service = ImportService(session, context)
        batch = service.preview_manual(
            account_id=account.id,
            platform=task.platform,
            content_type=ContentType.VIDEO,
            rows=[
                {
                    "title": f"扩展识别 {task.page_identifier}",
                    "body": "人工确认的合成扩展识别结果",
                    "published_at": task.collected_at.isoformat(),
                    "collected_at": task.collected_at.isoformat(),
                    "platform_content_id": task.page_identifier,
                    "metrics": metrics,
                    "metric_confidences": {
                        str(item["key"]): 1.0
                        for item in candidates
                        if isinstance(item, dict) and "key" in item
                    },
                }
            ],
        )
        row = service.rows(batch.id)[0]
        result = service.confirm(batch.id, [row.id])
        task.formal_snapshot_ids = list(cast(list[str], result["snapshot_ids"]))
    task.confirmed_at = datetime.now(UTC)
    task.confirmed_by = context.member_id
    clear_task_object(
        task,
        storage=storage if task.provider != "mock" else None,
    )
    session.commit()
    return task_payload(task, request_id=str(task.id))
