from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_session
from app.modules.models.capabilities import AdapterStatus, Capability
from app.modules.models.catalog import (
    ProviderCatalogEntry,
    QianwenRegion,
    list_catalog_entries,
)
from app.modules.models.config_service import (
    ModelConfigRead,
    ModelConfigService,
    ModelConfigurationRequired,
    SecretCipher,
)
from app.modules.models.connection_test import probe_qianwen_connection
from app.modules.models.openai_compatible_connection import (
    probe_openai_compatible_connection,
)
from app.modules.models.models import (
    ModelConfig,
    ModelContractValidationRun,
    ModelUsageAttempt,
    ModelUsagePolicy,
    ModelUsageReservation,
    ModelUsageReservationStatus,
)
from app.modules.models.usage import (
    ControlledValidationRequest,
    ControlledValidationService,
    ModelUsagePolicyInput,
    ModelUsagePolicyService,
)
from app.modules.workspace.permissions import Permission, require_permission
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.permissions import PermissionDenied
from app.core.security import WorkspaceContext


router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/model-configs",
    tags=["model-configs"],
)
usage_router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}",
    tags=["model-usage"],
)
DatabaseSession = Annotated[Session, Depends(get_session)]


class ModelConfigCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=80)
    model_id: str = Field(min_length=1, max_length=160)
    region: QianwenRegion | None = None
    provider_workspace_id: str | None = Field(default=None, min_length=1, max_length=80)
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    capabilities: frozenset[Capability] = Field(min_length=1)
    status: AdapterStatus
    api_key: SecretStr


class ModelConfigStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AdapterStatus


class ModelCatalogItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    capability: Capability
    contract_version: str
    experimental: bool
    upstream_snapshot_immutable: bool


class ModelCatalogRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    regions: list[QianwenRegion]
    models: list[ModelCatalogItem]


def _service(
    session: Session,
    workspace_id: UUID,
    session_token: str | None,
    csrf_token: str | None,
    *,
    mutation: bool,
) -> ModelConfigService:
    context = _workspace_context(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=mutation,
    )
    key = get_settings().model_secret_encryption_key.get_secret_value()
    return ModelConfigService(session, context, cipher=SecretCipher(key))


def _workspace_context(
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
        csrf_token is None or not auth.validate_csrf(session_token, csrf_token)
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return context


@router.get("/catalog", response_model=ModelCatalogRead)
def get_model_catalog(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> ModelCatalogRead:
    _service(
        session,
        workspace_id,
        session_token,
        None,
        mutation=False,
    )
    entries: tuple[ProviderCatalogEntry, ...] = list_catalog_entries()
    return ModelCatalogRead(
        provider="qianwen",
        regions=sorted(QianwenRegion, key=lambda item: item.value),
        models=[
            ModelCatalogItem(
                model_id=entry.model_id,
                capability=next(iter(entry.capabilities)),
                contract_version=entry.contract_version,
                experimental=True,
                upstream_snapshot_immutable=(
                    entry.upstream_snapshot_immutable is not False
                ),
            )
            for entry in entries
        ],
    )


@router.post("", response_model=ModelConfigRead, status_code=201)
def create_model_config(
    workspace_id: UUID,
    data: ModelConfigCreate,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> ModelConfigRead:
    service = _service(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=True,
    )
    try:
        config = service.save(
            provider=data.provider,
            model_id=data.model_id,
            capabilities=data.capabilities,
            status=data.status,
            api_key=data.api_key.get_secret_value(),
            region=data.region,
            provider_workspace_id=data.provider_workspace_id,
            display_name=data.display_name,
            base_url=data.base_url,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return service.public(config)


@router.get("", response_model=list[ModelConfigRead])
def list_model_configs(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[ModelConfigRead]:
    service = _service(
        session,
        workspace_id,
        session_token,
        None,
        mutation=False,
    )
    try:
        return service.list_public()
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error


@router.get("/selection", response_model=ModelConfigRead)
def select_model_config(
    workspace_id: UUID,
    capability: Capability,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> ModelConfigRead:
    service = _service(
        session,
        workspace_id,
        session_token,
        None,
        mutation=False,
    )
    try:
        return service.public(service.resolve({capability}))
    except ModelConfigurationRequired as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": error.code,
                "message": str(error),
                "action": error.action,
                "required_capabilities": [
                    item.value for item in error.required_capabilities
                ],
            },
        ) from error
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error


@router.patch("/{config_id}", response_model=ModelConfigRead)
def update_model_config_status(
    workspace_id: UUID,
    config_id: UUID,
    data: ModelConfigStatusUpdate,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> ModelConfigRead:
    service = _service(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=True,
    )
    try:
        config = service.set_status(config_id, data.status)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return service.public(config)


class ModelUsagePolicyRead(ModelUsagePolicyInput):
    id: UUID
    workspace_id: UUID
    version: int
    effective_from: datetime
    utc_day_boundary: str = "00:00:00Z"


class ModelUsageSummaryRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: UUID
    utc_day: str
    mock_attempts: int
    real_attempts: int
    estimated_cost_microunits: int
    settled_cost_microunits: int
    unknown_reserved_cost_microunits: int
    unknown_pricing_attempts: int
    currency: Literal["CNY"] = "CNY"
    sample_status: Literal["insufficient_sample", "available"]


class ModelUsageAttemptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    task_id: UUID
    attempt_id: UUID
    provider_attempt_number: int
    provider: str
    model_id: str
    region: str
    capability: str
    operation: str
    contract_version: str
    configuration_version: str
    pricing_version: str
    cost_known: bool
    usage_basis: Literal["estimated", "settled", "unknown"]
    status: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    image_inputs: int
    image_outputs: int
    embedding_inputs: int
    estimated_cost_microunits: int
    settled_cost_microunits: int | None
    currency: str
    latency_ms: int
    provider_request_id: str | None
    stable_error_code: str | None
    created_at: datetime


class ModelValidationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    workspace_id: UUID
    model_config_id: UUID
    region: str
    capability: str
    model_id: str
    contract_version: str
    configuration_version: str
    validation_suite_version: str
    max_calls: int
    max_input_tokens: int
    max_output_tokens: int
    max_images: int
    max_cost_microunits: int
    result: str
    safe_error_code: str | None
    evidence: dict[str, int | str | bool | None]
    started_at: datetime
    completed_at: datetime | None
    experimental: bool = True


def _policy_read(policy: ModelUsagePolicy) -> ModelUsagePolicyRead:
    return ModelUsagePolicyRead(
        id=policy.id,
        workspace_id=policy.workspace_id,
        capability=Capability(policy.capability),
        enabled=policy.enabled,
        max_concurrent_calls=policy.max_concurrent_calls,
        max_calls_per_minute=policy.max_calls_per_minute,
        daily_request_limit=policy.daily_request_limit,
        daily_input_token_limit=policy.daily_input_token_limit,
        daily_output_token_limit=policy.daily_output_token_limit,
        daily_embedding_token_limit=policy.daily_embedding_token_limit,
        daily_ocr_image_limit=policy.daily_ocr_image_limit,
        daily_generated_image_limit=policy.daily_generated_image_limit,
        daily_cost_limit_microunits=policy.daily_cost_limit_microunits,
        currency="CNY",
        version=policy.version,
        effective_from=policy.effective_from,
    )


def _usage_context(
    session: Session,
    workspace_id: UUID,
    session_token: str | None,
    csrf_token: str | None = None,
    *,
    mutation: bool,
) -> WorkspaceContext:
    context = _workspace_context(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=mutation,
    )
    try:
        require_permission(context.role, Permission.MANAGE_MODELS)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    return context


@usage_router.put(
    "/model-usage/policy",
    response_model=ModelUsagePolicyRead,
)
def save_model_usage_policy(
    workspace_id: UUID,
    data: ModelUsagePolicyInput,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> ModelUsagePolicyRead:
    context = _usage_context(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=True,
    )
    try:
        policy = ModelUsagePolicyService(session, context).save(data)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return _policy_read(policy)


@usage_router.get(
    "/model-usage/policy",
    response_model=list[ModelUsagePolicyRead],
)
def list_model_usage_policies(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[ModelUsagePolicyRead]:
    _usage_context(
        session,
        workspace_id,
        session_token,
        mutation=False,
    )
    rows = session.scalars(
        select(ModelUsagePolicy)
        .where(ModelUsagePolicy.workspace_id == workspace_id)
        .order_by(
            ModelUsagePolicy.capability,
            ModelUsagePolicy.version.desc(),
        )
    ).all()
    latest: dict[str, ModelUsagePolicy] = {}
    for row in rows:
        latest.setdefault(row.capability, row)
    return [_policy_read(latest[key]) for key in sorted(latest)]


@usage_router.get(
    "/model-usage/summary",
    response_model=ModelUsageSummaryRead,
)
def get_model_usage_summary(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> ModelUsageSummaryRead:
    _usage_context(
        session,
        workspace_id,
        session_token,
        mutation=False,
    )
    now = datetime.now(UTC)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    attempts = session.scalars(
        select(ModelUsageAttempt).where(
            ModelUsageAttempt.workspace_id == workspace_id,
            ModelUsageAttempt.created_at >= start,
        )
    ).all()
    unknown_reserved = session.scalar(
        select(
            func.coalesce(
                func.sum(ModelUsageReservation.reserved_cost_microunits),
                0,
            )
        ).where(
            ModelUsageReservation.workspace_id == workspace_id,
            ModelUsageReservation.created_at >= start,
            ModelUsageReservation.status
            == ModelUsageReservationStatus.UNKNOWN,
        )
    )
    return ModelUsageSummaryRead(
        workspace_id=workspace_id,
        utc_day=now.date().isoformat(),
        mock_attempts=0,
        real_attempts=len(attempts),
        estimated_cost_microunits=sum(
            row.estimated_cost_microunits for row in attempts
        ),
        settled_cost_microunits=sum(
            row.settled_cost_microunits or 0 for row in attempts
        ),
        unknown_reserved_cost_microunits=int(unknown_reserved or 0),
        unknown_pricing_attempts=sum(
            1 for row in attempts if not row.cost_known
        ),
        sample_status=(
            "available" if len(attempts) >= 10 else "insufficient_sample"
        ),
    )


@usage_router.get(
    "/model-usage/attempts",
    response_model=list[ModelUsageAttemptRead],
)
def list_model_usage_attempts(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[ModelUsageAttemptRead]:
    _usage_context(
        session,
        workspace_id,
        session_token,
        mutation=False,
    )
    rows = session.scalars(
        select(ModelUsageAttempt)
        .where(ModelUsageAttempt.workspace_id == workspace_id)
        .order_by(ModelUsageAttempt.created_at.desc(), ModelUsageAttempt.id)
        .limit(200)
    ).all()
    return [ModelUsageAttemptRead.model_validate(row) for row in rows]


@usage_router.post(
    "/model-validations",
    response_model=ModelValidationRead,
    status_code=201,
)
def create_model_validation(
    workspace_id: UUID,
    data: ControlledValidationRequest,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> ModelValidationRead:
    context = _usage_context(
        session,
        workspace_id,
        session_token,
        csrf_token,
        mutation=True,
    )
    cipher = SecretCipher(
        get_settings().model_secret_encryption_key.get_secret_value()
    )
    config_service = ModelConfigService(session, context, cipher=cipher)

    def connection_probe(config: ModelConfig) -> str | None:
        if config.provider == "qianwen":
            if config.region is None:
                return "MODEL_CONFIGURATION_REQUIRED"
            return probe_qianwen_connection(
                api_key=config_service.decrypt_key(config.id),
                region=QianwenRegion(config.region),
                provider_workspace_id=config.provider_workspace_id,
            )
        if (
            config.provider == "openai_compatible"
            and config.endpoint_base_url is not None
        ):
            return probe_openai_compatible_connection(
                api_key=config_service.decrypt_key(config.id),
                base_url=config.endpoint_base_url,
                model_id=config.model_id,
                app_env=get_settings().app_env,
            )
        return "MODEL_CONFIGURATION_REQUIRED"

    try:
        run = ControlledValidationService(
            session,
            context,
            real_calls_authorized=True,
            connection_probe=connection_probe,
        ).create(data)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="model config not found") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return ModelValidationRead.model_validate(run)


@usage_router.get(
    "/model-validations",
    response_model=list[ModelValidationRead],
)
def list_model_validations(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[ModelValidationRead]:
    _usage_context(
        session,
        workspace_id,
        session_token,
        mutation=False,
    )
    rows = session.scalars(
        select(ModelContractValidationRun)
        .where(ModelContractValidationRun.workspace_id == workspace_id)
        .order_by(
            ModelContractValidationRun.created_at.desc(),
            ModelContractValidationRun.id,
        )
    ).all()
    return [ModelValidationRead.model_validate(row) for row in rows]


@usage_router.get(
    "/model-validations/{validation_id}",
    response_model=ModelValidationRead,
)
def get_model_validation(
    workspace_id: UUID,
    validation_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> ModelValidationRead:
    _usage_context(
        session,
        workspace_id,
        session_token,
        mutation=False,
    )
    run = session.scalar(
        select(ModelContractValidationRun).where(
            ModelContractValidationRun.id == validation_id,
            ModelContractValidationRun.workspace_id == workspace_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="validation not found")
    return ModelValidationRead.model_validate(run)
