from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from app.core.storage import InvalidUploadToken, LocalStorage, get_storage
from app.main import app


def _storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(
        root=tmp_path / "objects",
        public_api_url="http://127.0.0.1:8000",
        token_secret="test-storage-secret-that-is-long-enough",
    )


def test_local_storage_supports_upload_confirm_and_download(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    payload = b"synthetic-image"
    grant = storage.issue_upload(
        workspace_id="workspace-1",
        content_id="content-1",
        category="cover",
        file_name="cover.png",
        mime_type="image/png",
        size=len(payload),
    )

    metadata = storage.verify_upload_token(grant.upload_token)
    storage.put_object(grant.object_key, payload, mime_type="image/png")

    assert metadata["workspace_id"] == "workspace-1"
    assert storage.get_object(grant.object_key) == payload
    assert storage.inspect_object(grant.object_key) is not None
    download_url, _ = storage.presign_download(grant.object_key)
    download_token = download_url.rsplit("/", 1)[-1]
    assert storage.verify_download_token(download_token) == grant.object_key


def test_local_storage_rejects_path_traversal_and_wrong_token_purpose(
    tmp_path: Path,
) -> None:
    storage = _storage(tmp_path)
    grant = storage.issue_upload(
        workspace_id="workspace-1",
        content_id="content-1",
        category="cover",
        file_name="cover.png",
        mime_type="image/png",
        size=1,
    )

    with pytest.raises(ValueError):
        storage.put_object("../../outside", b"x", mime_type="text/plain")
    with pytest.raises(InvalidUploadToken):
        storage.verify_download_token(grant.upload_token)


def test_local_storage_http_upload_and_download(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    payload = b"synthetic-image"
    grant = storage.issue_upload(
        workspace_id="workspace-1",
        content_id="content-1",
        category="cover",
        file_name="cover.png",
        mime_type="image/png",
        size=len(payload),
    )
    app.dependency_overrides[get_storage] = lambda: storage
    try:
        client = TestClient(app)
        uploaded = client.put(
            urlsplit(grant.upload_url).path,
            content=payload,
            headers={"Content-Type": "image/png"},
        )
        assert uploaded.status_code == 204

        download_url, _ = storage.presign_download(grant.object_key)
        downloaded = client.get(urlsplit(download_url).path)
        assert downloaded.status_code == 200
        assert downloaded.content == payload
        assert downloaded.headers["content-type"] == "image/png"
    finally:
        app.dependency_overrides.clear()
