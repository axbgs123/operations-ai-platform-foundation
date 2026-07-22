from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.modules.content.models import Content
from app.modules.style_facts.style_models import AccountStyleProfile, StyleSample
from app.modules.style_facts.style_service import (
    ProhibitedStyle,
    StyleInheritanceSwitches,
    StyleProfileRequired,
    StyleProfileService,
)
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.permissions import PermissionDenied


router = APIRouter(tags=["style-profiles"])
DatabaseSession = Annotated[Session, Depends(get_session)]


class StyleSampleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_id: UUID
    column_campaign_id: UUID | None = None


class StyleExtractionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column_campaign_id: UUID | None = None
    prohibited: ProhibitedStyle | None = None


class StyleSampleRead(BaseModel):
    id: UUID
    content_id: UUID
    title: str
    selected_by: UUID | None
    selected_at: datetime


class StyleCandidateRead(BaseModel):
    content_id: UUID
    title: str
    published_at: datetime | None
    selected: bool


class StyleProfileRead(BaseModel):
    id: UUID
    workspace_id: UUID
    account_id: UUID
    scope_key: str
    column_campaign_id: UUID | None
    version: int
    status: Literal["pending_confirmation", "confirmed"]
    style: dict[str, object]
    sample_sources: list[dict[str, object]]
    diff: dict[str, object]
    confirmed_by: UUID | None
    confirmed_at: datetime | None


class EffectiveStyleRead(BaseModel):
    source: Literal["account_default", "column_override"]
    profile_id: UUID
    version: int
    switches: StyleInheritanceSwitches
    style: dict[str, object]


def _service(
    session: Session,
    workspace_id: UUID,
    session_token: str | None,
    csrf_token: str | None,
    *,
    mutation: bool,
) -> StyleProfileService:
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
    return StyleProfileService(session, context)


def _sample_payload(sample: StyleSample, content: Content) -> dict[str, object]:
    return {
        "id": sample.id,
        "content_id": content.id,
        "title": content.published_title or content.title,
        "selected_by": sample.selected_by,
        "selected_at": sample.selected_at,
    }


def _profile_payload(
    session: Session,
    profile: AccountStyleProfile,
) -> dict[str, object]:
    content_ids = [UUID(value) for value in profile.sample_content_ids]
    contents = list(
        session.scalars(
            select(Content)
            .where(Content.id.in_(content_ids))
            .order_by(Content.published_at, Content.id)
        )
    )
    return {
        "id": profile.id,
        "workspace_id": profile.workspace_id,
        "account_id": profile.account_id,
        "scope_key": profile.scope_key,
        "column_campaign_id": profile.column_campaign_id,
        "version": profile.version,
        "status": profile.status.value,
        "style": profile.style,
        "sample_sources": [
            {
                "content_id": content.id,
                "title": content.published_title or content.title,
                "published_at": content.published_at,
            }
            for content in contents
        ],
        "diff": profile.diff,
        "confirmed_by": profile.confirmed_by,
        "confirmed_at": profile.confirmed_at,
    }


@router.post(
    "/v1/workspaces/{workspace_id}/accounts/{account_id}/style-samples",
    response_model=StyleSampleRead,
    status_code=201,
)
def select_style_sample(
    workspace_id: UUID,
    account_id: UUID,
    data: StyleSampleInput,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict[str, object]:
    service = _service(
        session, workspace_id, session_token, csrf_token, mutation=True
    )
    try:
        sample = service.select_sample(
            account_id, data.content_id, data.column_campaign_id
        )
        content = session.get(Content, sample.content_id)
        assert content is not None
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return _sample_payload(sample, content)


@router.get(
    "/v1/workspaces/{workspace_id}/accounts/{account_id}/style-samples",
    response_model=list[StyleSampleRead],
)
def list_style_samples(
    workspace_id: UUID,
    account_id: UUID,
    session: DatabaseSession,
    column_campaign_id: UUID | None = None,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[dict[str, object]]:
    service = _service(session, workspace_id, session_token, None, mutation=False)
    try:
        return [
            _sample_payload(sample, content)
            for sample, content in service.list_samples(
                account_id, column_campaign_id
            )
        ]
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get(
    "/v1/workspaces/{workspace_id}/accounts/{account_id}/style-samples/candidates",
    response_model=list[StyleCandidateRead],
)
def list_style_candidates(
    workspace_id: UUID,
    account_id: UUID,
    session: DatabaseSession,
    column_campaign_id: UUID | None = None,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[dict[str, object]]:
    service = _service(session, workspace_id, session_token, None, mutation=False)
    try:
        return [
            {
                "content_id": content.id,
                "title": content.published_title or content.title,
                "published_at": content.published_at,
                "selected": selected,
            }
            for content, selected in service.candidate_contents(
                account_id, column_campaign_id
            )
        ]
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post(
    "/v1/workspaces/{workspace_id}/accounts/{account_id}/style-profiles/extract",
    response_model=StyleProfileRead,
    status_code=201,
)
def extract_style_profile(
    workspace_id: UUID,
    account_id: UUID,
    data: StyleExtractionInput,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict[str, object]:
    service = _service(
        session, workspace_id, session_token, csrf_token, mutation=True
    )
    try:
        profile = service.extract_profile(
            account_id,
            data.column_campaign_id,
            data.prohibited,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return _profile_payload(session, profile)


@router.post(
    "/v1/workspaces/{workspace_id}/style-profiles/{profile_id}/confirm",
    response_model=StyleProfileRead,
)
def confirm_style_profile(
    workspace_id: UUID,
    profile_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict[str, object]:
    service = _service(
        session, workspace_id, session_token, csrf_token, mutation=True
    )
    try:
        profile = service.confirm_profile(profile_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    session.commit()
    return _profile_payload(session, profile)


@router.get(
    "/v1/workspaces/{workspace_id}/accounts/{account_id}/style-profiles",
    response_model=list[StyleProfileRead],
)
def list_style_profiles(
    workspace_id: UUID,
    account_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[dict[str, object]]:
    service = _service(session, workspace_id, session_token, None, mutation=False)
    try:
        profiles = service.list_profiles(account_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return [_profile_payload(session, profile) for profile in profiles]


@router.get(
    "/v1/workspaces/{workspace_id}/accounts/{account_id}/effective-style",
    response_model=EffectiveStyleRead,
)
def read_effective_style(
    workspace_id: UUID,
    account_id: UUID,
    session: DatabaseSession,
    column_campaign_id: UUID | None = None,
    at: datetime | None = None,
    inherit_title: bool = True,
    inherit_copy: bool = True,
    inherit_cover: bool = True,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> dict[str, object]:
    service = _service(session, workspace_id, session_token, None, mutation=False)
    switches = StyleInheritanceSwitches(
        title=inherit_title,
        copy=inherit_copy,
        cover=inherit_cover,
    )
    if at is not None and at.tzinfo is None:
        raise HTTPException(status_code=422, detail="timezone is required")
    try:
        profile, source = service.effective_profile(
            account_id,
            column_campaign_id=column_campaign_id,
            at=at,
        )
    except StyleProfileRequired as error:
        raise HTTPException(
            status_code=409,
            detail={"code": error.code, "message": str(error)},
        ) from error
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {
        "source": source,
        "profile_id": profile.id,
        "version": profile.version,
        "switches": switches,
        "style": service.filtered_style(profile, switches),
    }
