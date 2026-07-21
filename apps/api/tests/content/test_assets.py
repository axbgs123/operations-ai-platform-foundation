from datetime import UTC, datetime, timedelta

from app.core.storage import StoredObject, UploadGrant, get_storage
from tests.content.test_content_detail import configured_client, create_admin_and_account


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, StoredObject] = {}

    def issue_upload(self, **metadata) -> UploadGrant:
        key = f"test/{metadata['content_id']}/{metadata['file_name']}"
        return UploadGrant(
            object_key=key,
            upload_url=f"https://storage.test/{key}",
            upload_headers={"Content-Type": metadata["mime_type"]},
            upload_token=f"valid-token-for-{key}",
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )

    def verify_upload_token(self, token: str) -> dict:
        key = token.removeprefix("valid-token-for-")
        return {
            "object_key": key,
            "content_id": key.split("/")[1],
            "category": "cover",
            "file_name": key.split("/")[-1],
            "mime_type": "image/png",
            "size": 2048,
        }

    def inspect_object(self, object_key: str) -> StoredObject | None:
        return self.objects.get(object_key)

    def presign_download(self, object_key: str) -> tuple[str, datetime]:
        return (
            f"https://storage.test/download/{object_key}",
            datetime.now(UTC) + timedelta(minutes=5),
        )


def test_asset_presign_rejects_full_video_unknown_categories_and_large_files() -> None:
    with configured_client() as client:
        _, csrf, account = create_admin_and_account(client)
        content = client.post(
            "/v1/contents",
            headers={"X-CSRF-Token": csrf},
            json={
                "workspace_id": account["workspace_id"],
                "account_id": account["id"],
                "platform": "douyin",
                "title": "素材测试",
                "body": "测试",
            },
        ).json()
        endpoint = f"/v1/contents/{content['id']}/assets/presign"
        headers = {"X-CSRF-Token": csrf}

        video = client.post(
            endpoint,
            headers=headers,
            json={
                "category": "reference_image",
                "file_name": "full-video.mp4",
                "mime_type": "video/mp4",
                "size": 1024,
            },
        )
        assert video.status_code == 422
        gallery = client.post(
            endpoint,
            headers=headers,
            json={
                "category": "original_gallery",
                "file_name": "all-images.zip",
                "mime_type": "application/zip",
                "size": 1024,
            },
        )
        assert gallery.status_code == 422
        too_large = client.post(
            endpoint,
            headers=headers,
            json={
                "category": "cover",
                "file_name": "cover.png",
                "mime_type": "image/png",
                "size": 10 * 1024 * 1024 + 1,
            },
        )
        assert too_large.status_code == 422


def test_asset_is_persisted_only_after_storage_object_is_verified() -> None:
    storage = FakeStorage()
    with configured_client() as client:
        app = client.app
        app.dependency_overrides[get_storage] = lambda: storage
        _, csrf, account = create_admin_and_account(client)
        headers = {"X-CSRF-Token": csrf}
        created = client.post(
            "/v1/contents",
            headers=headers,
            json={
                "workspace_id": account["workspace_id"],
                "account_id": account["id"],
                "platform": "douyin",
                "title": "素材确认测试",
                "body": "测试",
            },
        ).json()
        content_id = created["id"]
        presigned = client.post(
            f"/v1/contents/{content_id}/assets/presign",
            headers=headers,
            json={
                "category": "cover",
                "file_name": "cover.png",
                "mime_type": "image/png",
                "size": 2048,
            },
        )
        assert presigned.status_code == 201
        grant = presigned.json()
        assert grant["upload_url"].startswith("https://storage.test/")
        assert grant["upload_headers"] == {"Content-Type": "image/png"}
        assert client.get(f"/v1/contents/{content_id}").json()["assets"] == []

        failed = client.post(
            f"/v1/contents/{content_id}/assets/confirm",
            headers=headers,
            json={"upload_token": grant["upload_token"]},
        )
        assert failed.status_code == 409
        assert client.get(f"/v1/contents/{content_id}").json()["assets"] == []

        storage.objects[grant["object_key"]] = StoredObject(
            size=2048, mime_type="image/png"
        )
        confirmed = client.post(
            f"/v1/contents/{content_id}/assets/confirm",
            headers=headers,
            json={"upload_token": grant["upload_token"]},
        )
        assert confirmed.status_code == 201
        asset = confirmed.json()
        assert asset["download_url"].startswith("https://storage.test/download/")
        assert asset["download_url_expires_at"] is not None
        assert len(client.get(f"/v1/contents/{content_id}").json()["assets"]) == 1
