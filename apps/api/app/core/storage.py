import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Protocol
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from app.core.config import get_settings


@dataclass(frozen=True)
class UploadGrant:
    object_key: str
    upload_url: str
    upload_headers: dict[str, str]
    upload_token: str
    expires_at: datetime


@dataclass(frozen=True)
class StoredObject:
    size: int
    mime_type: str


class Storage(Protocol):
    def issue_upload(self, **metadata) -> UploadGrant: ...
    def verify_upload_token(self, token: str) -> dict: ...
    def inspect_object(self, object_key: str) -> StoredObject | None: ...
    def presign_download(self, object_key: str) -> tuple[str, datetime]: ...
    def put_object(
        self,
        object_key: str,
        content: bytes,
        *,
        mime_type: str,
    ) -> None: ...
    def get_object(self, object_key: str) -> bytes: ...
    def delete_object(self, object_key: str) -> None: ...


class InvalidUploadToken(Exception):
    pass


class S3Storage:
    region = "us-east-1"
    service = "s3"

    def __init__(self) -> None:
        settings = get_settings()
        self._endpoint = settings.s3_endpoint.rstrip("/")
        self._public_endpoint = settings.s3_public_endpoint.rstrip("/")
        self._bucket = settings.s3_bucket
        self._access_key = settings.s3_access_key
        self._secret_key = settings.s3_secret_key
        self._token_secret = settings.storage_signing_secret.encode()
        self._bucket_ready = False
        self._opener = build_opener(ProxyHandler({}))

    @staticmethod
    def _sign(key: bytes, message: str) -> bytes:
        return hmac.new(key, message.encode(), hashlib.sha256).digest()

    def _presign(
        self,
        method: str,
        object_key: str | None,
        *,
        endpoint: str,
        expires: int,
        content_type: str | None = None,
    ) -> str:
        now = datetime.now(UTC)
        date = now.strftime("%Y%m%d")
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        credential_scope = f"{date}/{self.region}/{self.service}/aws4_request"
        parsed = urlsplit(endpoint)
        host = parsed.netloc
        path = f"/{quote(self._bucket, safe='')}"
        if object_key:
            path += f"/{quote(object_key, safe='/')}"
        signed_headers = "content-type;host" if content_type else "host"
        query = {
            "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
            "X-Amz-Credential": f"{self._access_key}/{credential_scope}",
            "X-Amz-Date": amz_date,
            "X-Amz-Expires": str(expires),
            "X-Amz-SignedHeaders": signed_headers,
        }
        canonical_query = urlencode(sorted(query.items()), quote_via=quote, safe="~")
        canonical_headers = ""
        if content_type:
            canonical_headers += f"content-type:{content_type.strip()}\n"
        canonical_headers += f"host:{host}\n"
        canonical_request = "\n".join(
            [
                method,
                path,
                canonical_query,
                canonical_headers,
                signed_headers,
                "UNSIGNED-PAYLOAD",
            ]
        )
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            ]
        )
        date_key = self._sign(f"AWS4{self._secret_key}".encode(), date)
        region_key = self._sign(date_key, self.region)
        service_key = self._sign(region_key, self.service)
        signing_key = self._sign(service_key, "aws4_request")
        signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
        return f"{endpoint}{path}?{canonical_query}&X-Amz-Signature={signature}"

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        url = self._presign("PUT", None, endpoint=self._endpoint, expires=60)
        try:
            with self._opener.open(
                Request(url, data=b"", method="PUT"), timeout=5
            ):
                pass
        except HTTPError as error:
            if error.code != 409:
                raise
        self._bucket_ready = True

    def ensure_bucket(self) -> None:
        """Create the configured bucket if it does not already exist."""
        self._ensure_bucket()

    def check_ready(self) -> None:
        url = self._presign("HEAD", None, endpoint=self._endpoint, expires=30)
        with self._opener.open(Request(url, method="HEAD"), timeout=2):
            pass

    def _encode_token(self, metadata: dict) -> str:
        payload = base64.urlsafe_b64encode(
            json.dumps(metadata, separators=(",", ":")).encode()
        ).decode().rstrip("=")
        signature = hmac.new(self._token_secret, payload.encode(), hashlib.sha256).hexdigest()
        return f"{payload}.{signature}"

    def issue_upload(self, **metadata) -> UploadGrant:
        self._ensure_bucket()
        expires_at = datetime.now(UTC) + timedelta(minutes=10)
        safe_name = metadata["file_name"].replace("/", "_").replace("\\", "_")
        object_key = (
            f"workspaces/{metadata['workspace_id']}/contents/{metadata['content_id']}/"
            f"{secrets.token_hex(12)}-{safe_name}"
        )
        token_metadata = {
            **{key: str(value) for key, value in metadata.items()},
            "object_key": object_key,
            "expires_at": int(expires_at.timestamp()),
        }
        upload_url = self._presign(
            "PUT",
            object_key,
            endpoint=self._public_endpoint,
            expires=600,
            content_type=metadata["mime_type"],
        )
        return UploadGrant(
            object_key=object_key,
            upload_url=upload_url,
            upload_headers={"Content-Type": metadata["mime_type"]},
            upload_token=self._encode_token(token_metadata),
            expires_at=expires_at,
        )

    def verify_upload_token(self, token: str) -> dict:
        try:
            payload, signature = token.rsplit(".", 1)
            expected = hmac.new(
                self._token_secret, payload.encode(), hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise InvalidUploadToken
            padded = payload + "=" * (-len(payload) % 4)
            metadata = json.loads(base64.urlsafe_b64decode(padded))
            if int(metadata["expires_at"]) < int(datetime.now(UTC).timestamp()):
                raise InvalidUploadToken
            return metadata
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise InvalidUploadToken from error

    def inspect_object(self, object_key: str) -> StoredObject | None:
        url = self._presign("HEAD", object_key, endpoint=self._endpoint, expires=60)
        try:
            with self._opener.open(Request(url, method="HEAD"), timeout=5) as response:
                return StoredObject(
                    size=int(response.headers.get("Content-Length", "0")),
                    mime_type=response.headers.get("Content-Type", "").split(";", 1)[0],
                )
        except HTTPError as error:
            if error.code == 404:
                return None
            raise

    def put_object(
        self,
        object_key: str,
        content: bytes,
        *,
        mime_type: str,
    ) -> None:
        self._ensure_bucket()
        url = self._presign(
            "PUT",
            object_key,
            endpoint=self._endpoint,
            expires=60,
            content_type=mime_type,
        )
        request = Request(
            url,
            data=content,
            method="PUT",
            headers={"Content-Type": mime_type},
        )
        with self._opener.open(request, timeout=10):
            pass

    def get_object(self, object_key: str) -> bytes:
        url = self._presign(
            "GET",
            object_key,
            endpoint=self._endpoint,
            expires=60,
        )
        try:
            with self._opener.open(
                Request(url, method="GET"),
                timeout=10,
            ) as response:
                return response.read()
        except HTTPError as error:
            if error.code == 404:
                raise FileNotFoundError(object_key) from error
            raise

    def delete_object(self, object_key: str) -> None:
        url = self._presign(
            "DELETE",
            object_key,
            endpoint=self._endpoint,
            expires=60,
        )
        try:
            with self._opener.open(
                Request(url, method="DELETE"),
                timeout=10,
            ):
                pass
        except HTTPError as error:
            if error.code != 404:
                raise

    def presign_download(self, object_key: str) -> tuple[str, datetime]:
        expires_at = datetime.now(UTC) + timedelta(minutes=5)
        return (
            self._presign(
                "GET", object_key, endpoint=self._public_endpoint, expires=300
            ),
            expires_at,
        )


@lru_cache
def get_storage() -> Storage:
    return S3Storage()
