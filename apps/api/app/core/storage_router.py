from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from app.core.storage import (
    InvalidUploadToken,
    LocalStorage,
    Storage,
    get_storage,
)


router = APIRouter(prefix="/v1/local-storage", tags=["local-storage"])
ObjectStorage = Annotated[Storage, Depends(get_storage)]


def _local(storage: Storage) -> LocalStorage:
    if not isinstance(storage, LocalStorage):
        raise HTTPException(status_code=404, detail="local storage unavailable")
    return storage


@router.put("/uploads/{token}", status_code=204)
async def upload_local_object(
    token: str,
    request: Request,
    storage: ObjectStorage,
    content_type: Annotated[str | None, Header(alias="Content-Type")] = None,
) -> Response:
    local = _local(storage)
    try:
        metadata = local.verify_upload_token(token)
    except InvalidUploadToken as error:
        raise HTTPException(status_code=401, detail="invalid upload token") from error
    expected_size = int(metadata["size"])
    expected_type = str(metadata["mime_type"])
    if content_type is None or content_type.split(";", 1)[0] != expected_type:
        raise HTTPException(status_code=409, detail="uploaded object metadata mismatch")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > expected_size:
            raise HTTPException(status_code=413, detail="uploaded object is too large")
        chunks.append(chunk)
    if size != expected_size:
        raise HTTPException(status_code=409, detail="uploaded object metadata mismatch")
    local.put_object(
        str(metadata["object_key"]),
        b"".join(chunks),
        mime_type=expected_type,
    )
    return Response(status_code=204)


@router.get("/downloads/{token}")
def download_local_object(token: str, storage: ObjectStorage) -> Response:
    local = _local(storage)
    try:
        object_key = local.verify_download_token(token)
        stored = local.inspect_object(object_key)
        if stored is None:
            raise FileNotFoundError(object_key)
        content = local.get_object(object_key)
    except InvalidUploadToken as error:
        raise HTTPException(status_code=401, detail="invalid download token") from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="object not found") from error
    return Response(content=content, media_type=stored.mime_type)
