from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.modules.content.account_models import ColumnCampaignKind, Platform
from app.modules.content.account_service import AccountConfigurationService
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.permissions import PermissionDenied


router = APIRouter(prefix="/v1/workspaces/{workspace_id}", tags=["accounts"])
DatabaseSession = Annotated[Session, Depends(get_session)]


class ConfigurationInput(BaseModel):
    objectives: list[str] = Field(min_length=1, max_length=20)
    metric_weights: dict[str, float] = Field(min_length=1, max_length=30)
    benchmark_sample_size: int = Field(ge=1, le=500)


class AccountCreate(ConfigurationInput):
    platform: Literal["douyin", "xiaohongshu"]
    name: str = Field(min_length=1, max_length=120)


class AccountUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ColumnCampaignUpdate(BaseModel):
    restore_account_defaults: Literal[True]


class ColumnCampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["column", "campaign"]
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    objectives: list[str] | None = None
    metric_weights: dict[str, float] | None = None
    benchmark_sample_size: int | None = Field(default=None, ge=1, le=500)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timezone is required")
        return value

    @model_validator(mode="after")
    def validate_window(self):
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


def _service(
    session: Session,
    workspace_id: UUID,
    session_token: str | None,
    csrf_token: str | None,
    *,
    mutation: bool,
) -> AccountConfigurationService:
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
    return AccountConfigurationService(session, context)


def _objective(profile) -> dict:
    return {
        "id": profile.id,
        "version": profile.version,
        "objectives": profile.objectives,
        "metric_weights": profile.metric_weights,
    }


def _benchmark(profile) -> dict:
    return {
        "id": profile.id,
        "version": profile.version,
        "sample_size": profile.sample_size,
    }


def _account_payload(account, objective, benchmark) -> dict:
    return {
        "id": account.id,
        "workspace_id": account.workspace_id,
        "platform": account.platform.value,
        "name": account.name,
        "objective_profile": _objective(objective),
        "benchmark_profile": _benchmark(benchmark),
    }


def _column_campaign_payload(item) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "kind": item.kind.value,
        "starts_at": item.starts_at,
        "ends_at": item.ends_at,
        "objective_profile_id": item.objective_profile_id,
        "benchmark_profile_id": item.benchmark_profile_id,
    }


@router.post("/accounts", status_code=201)
def create_account(
    workspace_id: UUID,
    data: AccountCreate,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    service = _service(session, workspace_id, session_token, csrf_token, mutation=True)
    try:
        account, objective, benchmark = service.create_account(
            Platform(data.platform),
            data.name,
            data.objectives,
            data.metric_weights,
            data.benchmark_sample_size,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return _account_payload(account, objective, benchmark)


@router.get("/accounts")
def list_accounts(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[dict]:
    service = _service(session, workspace_id, session_token, None, mutation=False)
    try:
        accounts = service.list_accounts()
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    return [
        {
            "id": account.id,
            "workspace_id": account.workspace_id,
            "platform": account.platform.value,
            "name": account.name,
        }
        for account in accounts
    ]


@router.patch("/accounts/{account_id}")
def update_account(
    workspace_id: UUID,
    account_id: UUID,
    data: AccountUpdate,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    service = _service(session, workspace_id, session_token, csrf_token, mutation=True)
    try:
        account = service.rename_account(account_id, data.name)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    session.commit()
    return {
        "id": account.id,
        "workspace_id": account.workspace_id,
        "platform": account.platform.value,
        "name": account.name,
    }


@router.delete("/accounts/{account_id}", status_code=204)
def delete_account(
    workspace_id: UUID,
    account_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> Response:
    service = _service(session, workspace_id, session_token, csrf_token, mutation=True)
    try:
        service.delete_account(account_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    session.commit()
    return Response(status_code=204)


@router.patch("/accounts/{account_id}/configuration")
def update_account_configuration(
    workspace_id: UUID,
    account_id: UUID,
    data: ConfigurationInput,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    service = _service(session, workspace_id, session_token, csrf_token, mutation=True)
    try:
        account, objective, benchmark = service.update_configuration(
            account_id,
            data.objectives,
            data.metric_weights,
            data.benchmark_sample_size,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return _account_payload(account, objective, benchmark)


@router.get("/accounts/{account_id}/configuration/versions")
def read_configuration_versions(
    workspace_id: UUID,
    account_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> dict:
    service = _service(session, workspace_id, session_token, None, mutation=False)
    try:
        objectives, benchmarks = service.versions(account_id)
    except (LookupError, PermissionDenied) as error:
        status = 404 if isinstance(error, LookupError) else 403
        raise HTTPException(status_code=status, detail=str(error)) from error
    return {
        "objectives": [_objective(item) for item in objectives],
        "benchmarks": [_benchmark(item) for item in benchmarks],
    }


@router.post("/accounts/{account_id}/columns-campaigns", status_code=201)
def create_column_campaign(
    workspace_id: UUID,
    account_id: UUID,
    data: ColumnCampaignCreate,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    service = _service(session, workspace_id, session_token, csrf_token, mutation=True)
    try:
        item = service.create_column_campaign(
            account_id,
            name=data.name,
            kind=ColumnCampaignKind(data.kind),
            starts_at=data.starts_at,
            ends_at=data.ends_at,
            objectives=data.objectives,
            metric_weights=data.metric_weights,
            benchmark_sample_size=data.benchmark_sample_size,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return _column_campaign_payload(item)


@router.get("/accounts/{account_id}/columns-campaigns")
def list_column_campaigns(
    workspace_id: UUID,
    account_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[dict]:
    service = _service(session, workspace_id, session_token, None, mutation=False)
    try:
        items = service.list_column_campaigns(account_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return [_column_campaign_payload(item) for item in items]


@router.patch("/accounts/{account_id}/columns-campaigns/{item_id}")
def update_column_campaign(
    workspace_id: UUID,
    account_id: UUID,
    item_id: UUID,
    data: ColumnCampaignUpdate,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    service = _service(session, workspace_id, session_token, csrf_token, mutation=True)
    try:
        item = service.restore_column_campaign_defaults(account_id, item_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    session.commit()
    return _column_campaign_payload(item)


@router.delete("/accounts/{account_id}/columns-campaigns/{item_id}", status_code=204)
def delete_column_campaign(
    workspace_id: UUID,
    account_id: UUID,
    item_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> Response:
    service = _service(session, workspace_id, session_token, csrf_token, mutation=True)
    try:
        service.delete_column_campaign(account_id, item_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    session.commit()
    return Response(status_code=204)


@router.get("/accounts/{account_id}/effective-configuration")
def read_effective_configuration(
    workspace_id: UUID,
    account_id: UUID,
    session: DatabaseSession,
    column_campaign_id: UUID | None = None,
    at: datetime | None = None,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> dict:
    service = _service(session, workspace_id, session_token, None, mutation=False)
    try:
        effective = service.effective_configuration(
            account_id,
            column_campaign_id=column_campaign_id,
            at=at or datetime.now(UTC),
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {
        "source": effective.source,
        "objective_profile": _objective(effective.objective_profile),
        "benchmark_profile": _benchmark(effective.benchmark_profile),
    }
