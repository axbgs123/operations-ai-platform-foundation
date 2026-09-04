from __future__ import annotations

from datetime import UTC, datetime
import re
import httpx

from app.modules.content.account_models import Platform
from app.modules.public_data.contracts import (
    PublicDataProvider,
    PublicMetricObservation,
    PublicProviderError,
    ResolvedPublicContent,
)


TIKHUB_API_BASES = {
    "china": "https://api.tikhub.dev",
    "global": "https://api.tikhub.io",
}


def _walk_dicts(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _first_value(value: object, *keys: str) -> object | None:
    for item in _walk_dicts(value):
        for key in keys:
            if key in item and item[key] is not None:
                return item[key]
    return None


def _count(value: object, *keys: str) -> int | float | None:
    candidate = _first_value(value, *keys)
    if isinstance(candidate, bool) or candidate is None:
        return None
    if isinstance(candidate, (int, float)):
        return candidate
    if isinstance(candidate, str):
        cleaned = candidate.replace(",", "").strip()
        try:
            return float(cleaned) if "." in cleaned else int(cleaned)
        except ValueError:
            return None
    return None


class TikHubProvider(PublicDataProvider):
    name = "tikhub"

    def __init__(
        self,
        *,
        api_key: str,
        endpoint_region: str,
        timeout_seconds: float = 45,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if endpoint_region not in TIKHUB_API_BASES:
            raise ValueError("unsupported TikHub endpoint region")
        self._client = httpx.Client(
            base_url=TIKHUB_API_BASES[endpoint_region],
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_seconds,
            transport=transport,
        )

    def _request(
        self,
        path: str,
        params: dict[str, str | int | float | bool | None] | None = None,
    ) -> dict[str, object]:
        try:
            response = self._client.get(path, params=params)
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise PublicProviderError(
                "PUBLIC_PROVIDER_TIMEOUT", retryable=True
            ) from error
        if response.status_code in {401, 403}:
            raise PublicProviderError("PUBLIC_PROVIDER_AUTH_FAILED", retryable=False)
        if response.status_code == 429:
            raise PublicProviderError("PUBLIC_PROVIDER_RATE_LIMITED", retryable=True)
        if response.status_code == 404:
            raise PublicProviderError("PUBLIC_CONTENT_NOT_FOUND", retryable=False)
        if response.status_code >= 500:
            raise PublicProviderError("PUBLIC_PROVIDER_UNAVAILABLE", retryable=True)
        try:
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise PublicProviderError(
                "PUBLIC_PROVIDER_INVALID_RESPONSE", retryable=False
            ) from error
        if not isinstance(payload, dict):
            raise PublicProviderError(
                "PUBLIC_PROVIDER_INVALID_RESPONSE", retryable=False
            )
        code = payload.get("code")
        if code not in {None, 0, 200}:
            message = str(payload.get("message", "")).lower()
            retryable = any(word in message for word in ("timeout", "limit", "busy"))
            raise PublicProviderError(
                "PUBLIC_PROVIDER_REJECTED"
                if not retryable
                else "PUBLIC_PROVIDER_UNAVAILABLE",
                retryable=retryable,
            )
        return payload

    def test_connection(self) -> str | None:
        payload = self._request("/api/v1/tikhub/user/get_user_info")
        request_id = payload.get("request_id")
        return request_id if isinstance(request_id, str) else None

    def resolve_content(
        self,
        *,
        platform: Platform,
        public_url: str,
        platform_content_id: str | None = None,
    ) -> ResolvedPublicContent:
        if platform_content_id:
            return ResolvedPublicContent(
                platform=platform,
                platform_content_id=platform_content_id,
                public_url=public_url,
                locator={"content_id": platform_content_id},
            )
        if platform is Platform.DOUYIN:
            payload = self._request(
                "/api/v1/douyin/web/fetch_one_video_by_share_url",
                {"share_url": public_url},
            )
            content_id = _first_value(payload.get("data"), "aweme_id")
            if not isinstance(content_id, (str, int)):
                raise PublicProviderError("PUBLIC_CONTENT_ID_MISSING", retryable=False)
            return ResolvedPublicContent(
                platform=platform,
                platform_content_id=str(content_id),
                public_url=public_url,
                locator={"content_id": str(content_id)},
            )
        payload = self._request(
            "/api/v1/xiaohongshu/web/get_note_id_and_xsec_token",
            {"share_text": public_url},
        )
        note_id = _first_value(payload.get("data"), "note_id", "noteId")
        xsec_token = _first_value(payload.get("data"), "xsec_token", "xsecToken")
        if not isinstance(note_id, (str, int)):
            raise PublicProviderError("PUBLIC_CONTENT_ID_MISSING", retryable=False)
        locator = {"content_id": str(note_id)}
        if isinstance(xsec_token, str) and xsec_token:
            locator["xsec_token"] = xsec_token
        return ResolvedPublicContent(
            platform=platform,
            platform_content_id=str(note_id),
            public_url=public_url,
            locator=locator,
        )

    def fetch_content_metrics(
        self,
        *,
        platform: Platform,
        locator: dict[str, str],
    ) -> PublicMetricObservation:
        content_id = locator["content_id"]
        if platform is Platform.DOUYIN:
            path = "/api/v1/douyin/app/v3/fetch_one_video"
            payload = self._request(path, {"aweme_id": content_id})
            metrics = {
                "views": _count(payload.get("data"), "play_count"),
                "likes": _count(payload.get("data"), "digg_count", "like_count"),
                "comments": _count(payload.get("data"), "comment_count"),
                "favorites": _count(payload.get("data"), "collect_count"),
                "shares": _count(payload.get("data"), "share_count"),
            }
            contract = "tikhub-douyin-app-v3-video-v1"
        else:
            path = "/api/v1/xiaohongshu/web_v3/fetch_note_detail"
            params: dict[str, str | int | float | bool | None] = {"note_id": content_id}
            if locator.get("xsec_token"):
                params["xsec_token"] = locator["xsec_token"]
            payload = self._request(path, params)
            metrics = {
                "views": _count(payload.get("data"), "view_count", "viewCount"),
                "likes": _count(payload.get("data"), "liked_count", "like_count"),
                "comments": _count(payload.get("data"), "comment_count"),
                "favorites": _count(
                    payload.get("data"), "collected_count", "collect_count"
                ),
                "shares": _count(payload.get("data"), "share_count"),
            }
            contract = "tikhub-xiaohongshu-web-v3-note-v1"
        request_id = payload.get("request_id")
        return PublicMetricObservation(
            endpoint_contract=contract,
            provider_request_id=request_id if isinstance(request_id, str) else None,
            fetched_at=datetime.now(UTC),
            raw_response=payload,
            metrics=metrics,
        )


class MockPublicDataProvider(PublicDataProvider):
    name = "mock"

    def test_connection(self) -> str | None:
        return "mock-public-data-request"

    def resolve_content(
        self,
        *,
        platform: Platform,
        public_url: str,
        platform_content_id: str | None = None,
    ) -> ResolvedPublicContent:
        resolved_id = platform_content_id
        if not resolved_id:
            match = re.search(r"([A-Za-z0-9]{12,})", public_url)
            resolved_id = match.group(1) if match else f"mock-{platform.value}-content"
        return ResolvedPublicContent(
            platform=platform,
            platform_content_id=resolved_id,
            public_url=public_url,
            locator={"content_id": resolved_id},
        )

    def fetch_content_metrics(
        self,
        *,
        platform: Platform,
        locator: dict[str, str],
    ) -> PublicMetricObservation:
        metrics: dict[str, int | float | None] = {
            "views": 1200,
            "likes": 128,
            "comments": 18,
            "favorites": 36,
            "shares": 12,
        }
        return PublicMetricObservation(
            endpoint_contract=f"mock-{platform.value}-public-metrics-v1",
            provider_request_id="mock-public-data-request",
            fetched_at=datetime.now(UTC),
            raw_response={
                "code": 200,
                "data": {"id": locator["content_id"], **metrics},
            },
            metrics=metrics,
        )
