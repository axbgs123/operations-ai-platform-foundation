from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.storage import InvalidUploadToken, Storage, get_storage
from app.modules.content.account_models import ColumnCampaign, Platform, PlatformAccount
from app.modules.content.models import AssetCategory, Content, ContentAsset
from app.modules.content.schemas import (
    AssetConfirmRequest,
    AssetPresignRequest,
    AssetRead,
    AssetUploadGrantRead,
    ContentCreate,
    ContentRead,
    ContentUpdate,
)
from app.modules.content.service import ContentService
from app.modules.metrics.models import ContentType
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.permissions import PermissionDenied


router = APIRouter(prefix="/v1/contents", tags=["contents"])
DatabaseSession = Annotated[Session, Depends(get_session)]
ObjectStorage = Annotated[Storage, Depends(get_storage)]


def _service(
    session: Session,
    session_token: str | None,
    csrf_token: str | None,
    *,
    mutation: bool,
    workspace_id: UUID | None = None,
) -> ContentService:
    if session_token is None:
        raise HTTPException(status_code=401, detail="invalid session")
    auth = InviteAuthService(session)
    context = auth.authenticate(session_token)
    if context is None:
        raise HTTPException(status_code=401, detail="invalid session")
    if workspace_id is not None and context.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="workspace not found")
    if mutation and (
        csrf_token is None or not auth.validate_csrf(session_token, csrf_token)
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return ContentService(session, context)


def _asset_payload(asset: ContentAsset, storage: Storage | None = None) -> dict:
    download_url = None
    download_expires_at = None
    if storage is not None:
        download_url, download_expires_at = storage.presign_download(asset.object_key)
    return {
        "id": asset.id,
        "category": asset.category.value,
        "file_name": asset.file_name,
        "mime_type": asset.mime_type,
        "size": asset.size,
        "download_url": download_url,
        "download_url_expires_at": download_expires_at,
    }


def _payload(session: Session, content: Content, storage: Storage | None = None) -> dict:
    account = session.get(PlatformAccount, content.account_id)
    column_campaign = (
        session.get(ColumnCampaign, content.column_campaign_id)
        if content.column_campaign_id
        else None
    )
    assets = list(
        session.scalars(
            select(ContentAsset).where(ContentAsset.content_id == content.id)
        )
    )
    return {
        "id": content.id,
        "workspace_id": content.workspace_id,
        "account_id": content.account_id,
        "account_name": account.name if account else "",
        "platform": content.platform.value,
        "content_type": content.content_type.value,
        "title": content.title,
        "body": content.body,
        "status": content.status.value,
        "column_campaign_id": content.column_campaign_id,
        "column_campaign_name": column_campaign.name if column_campaign else None,
        "work_url": content.work_url,
        "platform_content_id": content.platform_content_id,
        "published_title": content.published_title,
        "published_body": content.published_body,
        "published_at": content.published_at,
        "deleted_at": content.deleted_at,
        "objective_profile_id": content.objective_profile_id,
        "benchmark_profile_id": content.benchmark_profile_id,
        "assets": [_asset_payload(asset, storage) for asset in assets],
    }


@router.post("", response_model=ContentRead, status_code=201)
def create_content(
    data: ContentCreate,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    service = _service(
        session,
        session_token,
        csrf_token,
        mutation=True,
        workspace_id=data.workspace_id,
    )
    try:
        content = service.create(
            account_id=data.account_id,
            platform=Platform(data.platform),
            content_type=ContentType(data.content_type),
            title=data.title,
            body=data.body,
            column_campaign_id=data.column_campaign_id,
            work_url=str(data.work_url) if data.work_url else None,
        )
        content.platform_content_id = data.platform_content_id
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return _payload(session, content)


@router.get("", response_model=list[ContentRead])
def list_contents(
    workspace_id: UUID,
    session: DatabaseSession,
    storage: ObjectStorage,
    trash: bool = False,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[dict]:
    service = _service(
        session, session_token, None, mutation=False, workspace_id=workspace_id
    )
    try:
        contents = service.list(trash=trash)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    return [_payload(session, content, storage) for content in contents]


@router.get("/{content_id}", response_model=ContentRead)
def read_content(
    content_id: UUID,
    session: DatabaseSession,
    storage: ObjectStorage,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> dict:
    service = _service(session, session_token, None, mutation=False)
    try:
        content = service.read(content_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return _payload(session, content, storage)


@router.patch("/{content_id}", response_model=ContentRead)
def update_content(
    content_id: UUID,
    data: ContentUpdate,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    service = _service(session, session_token, csrf_token, mutation=True)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("work_url") is not None:
        changes["work_url"] = str(changes["work_url"])
    try:
        content = service.update(content_id, changes=changes)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return _payload(session, content)


@router.delete("/{content_id}", status_code=204)
def delete_content(
    content_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> Response:
    service = _service(session, session_token, csrf_token, mutation=True)
    try:
        service.delete(content_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    session.commit()
    return Response(status_code=204)


@router.post(
    "/{content_id}/assets/presign",
    response_model=AssetUploadGrantRead,
    status_code=201,
)
def presign_asset(
    content_id: UUID,
    data: AssetPresignRequest,
    session: DatabaseSession,
    storage: ObjectStorage,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    service = _service(session, session_token, csrf_token, mutation=True)
    try:
        content = service.prepare_asset(content_id, AssetCategory(data.category))
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    grant = storage.issue_upload(
        workspace_id=content.workspace_id,
        content_id=content.id,
        category=data.category,
        file_name=data.file_name,
        mime_type=data.mime_type,
        size=data.size,
    )
    return {
        "object_key": grant.object_key,
        "upload_url": grant.upload_url,
        "upload_headers": grant.upload_headers,
        "upload_token": grant.upload_token,
        "expires_at": grant.expires_at,
    }


@router.post(
    "/{content_id}/assets/confirm",
    response_model=AssetRead,
    status_code=201,
)
def confirm_asset(
    content_id: UUID,
    data: AssetConfirmRequest,
    session: DatabaseSession,
    storage: ObjectStorage,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    service = _service(session, session_token, csrf_token, mutation=True)
    try:
        metadata = storage.verify_upload_token(data.upload_token)
        if UUID(str(metadata["content_id"])) != content_id:
            raise InvalidUploadToken
        stored = storage.inspect_object(str(metadata["object_key"]))
        if stored is None:
            raise HTTPException(status_code=409, detail="uploaded object not found")
        if stored.size != int(metadata["size"]) or stored.mime_type != metadata["mime_type"]:
            raise HTTPException(status_code=409, detail="uploaded object metadata mismatch")
        asset = service.confirm_asset(
            content_id,
            category=AssetCategory(metadata["category"]),
            object_key=str(metadata["object_key"]),
            file_name=str(metadata["file_name"]),
            mime_type=str(metadata["mime_type"]),
            size=int(metadata["size"]),
        )
    except InvalidUploadToken as error:
        raise HTTPException(status_code=401, detail="invalid upload token") from error
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return _asset_payload(asset, storage)
