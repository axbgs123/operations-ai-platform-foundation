from __future__ import annotations

from datetime import UTC, datetime
import re
import httpx

from app.modules.content.account_models import Platform
from app.modules.public_data.contracts import (
    PublicAccountObservation,
    PublicCommentObservation,
    PublicDataProvider,
    PublicMetricObservation,
    PublicProviderError,
    PublicSearchObservation,
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


def _first_list(value: object, *keys: str) -> list[object]:
    for item in _walk_dicts(value):
        for key in keys:
            candidate = item.get(key)
            if isinstance(candidate, list):
                return candidate
    return []


def _normalized_post(value: object, platform: Platform) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    content_id = _first_value(value, "aweme_id", "note_id", "noteId")
    if content_id is None:
        direct_id = value.get("id")
        content_id = direct_id if isinstance(direct_id, (str, int)) else None
    if not isinstance(content_id, (str, int)):
        return None
    title = _first_value(value, "desc", "display_title", "displayTitle", "title")
    published_at = _first_value(value, "create_time", "time", "publish_time")
    public_url = _first_value(value, "share_url", "note_url", "jump_url", "web_url")
    if not isinstance(public_url, str) or not public_url.startswith("https://"):
        public_url = (
            f"https://www.douyin.com/video/{content_id}"
            if platform is Platform.DOUYIN
            else f"https://www.xiaohongshu.com/explore/{content_id}"
        )
    return {
        "content_id": str(content_id),
        "public_url": public_url,
        "title": str(title)[:300] if isinstance(title, (str, int)) else "未提供标题",
        "published_at": published_at
        if isinstance(published_at, (str, int, float))
        else None,
        "views": _count(value, "play_count", "view_count", "viewCount"),
        "likes": _count(value, "digg_count", "liked_count", "like_count", "likedCount"),
        "comments": _count(value, "comment_count", "commentCount"),
        "favorites": _count(
            value, "collect_count", "collected_count", "collectedCount"
        ),
        "shares": _count(value, "share_count", "shareCount"),
    }


def _comment_texts(payload: object) -> list[str]:
    candidates = _first_list(payload, "comments", "comment_list", "commentList")
    output: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        text = _first_value(candidate, "text", "content", "comment_text")
        if not isinstance(text, str):
            continue
        normalized = " ".join(text.split()).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized[:500])
        if len(output) >= 100:
            break
    return output


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
        *,
        method: str = "GET",
        json_body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        try:
            response = self._client.request(
                method,
                path,
                params=params,
                json=json_body,
            )
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

    def fetch_account_posts(
        self,
        *,
        platform: Platform,
        platform_account_id: str,
    ) -> PublicAccountObservation:
        if platform is Platform.DOUYIN:
            path = "/api/v1/douyin/app/v3/fetch_user_post_videos"
            payload = self._request(
                path,
                {"sec_user_id": platform_account_id, "max_cursor": 0, "count": 20},
            )
            candidates = _first_list(payload.get("data"), "aweme_list", "items")
            contract = "tikhub-douyin-app-v3-user-posts-v1"
        else:
            path = "/api/v1/xiaohongshu/web_v3/fetch_user_notes"
            payload = self._request(
                path,
                {"user_id": platform_account_id, "cursor": "", "num": 20},
            )
            candidates = _first_list(payload.get("data"), "notes", "items")
            contract = "tikhub-xiaohongshu-web-v3-user-notes-v1"
        posts = [
            post for item in candidates if (post := _normalized_post(item, platform))
        ]
        request_id = payload.get("request_id")
        return PublicAccountObservation(
            endpoint_contract=contract,
            provider_request_id=request_id if isinstance(request_id, str) else None,
            fetched_at=datetime.now(UTC),
            raw_response=payload,
            follower_count=_count(
                payload.get("data"), "follower_count", "fans_count", "fans"
            ),
            posts=posts,
        )

    def fetch_content_comments(
        self,
        *,
        platform: Platform,
        locator: dict[str, str],
    ) -> PublicCommentObservation:
        content_id = locator["content_id"]
        if platform is Platform.DOUYIN:
            path = "/api/v1/douyin/app/v3/fetch_video_comments"
            payload = self._request(
                path, {"aweme_id": content_id, "cursor": 0, "count": 50}
            )
            contract = "tikhub-douyin-app-v3-comments-v1"
        else:
            path = "/api/v1/xiaohongshu/web_v3/fetch_note_comments"
            payload = self._request(path, {"note_id": content_id, "cursor": ""})
            contract = "tikhub-xiaohongshu-web-v3-comments-v1"
        request_id = payload.get("request_id")
        return PublicCommentObservation(
            endpoint_contract=contract,
            provider_request_id=request_id if isinstance(request_id, str) else None,
            fetched_at=datetime.now(UTC),
            raw_response=payload,
            comments=_comment_texts(payload.get("data")),
        )

    def search_public_content(
        self,
        *,
        platform: Platform,
        keyword: str,
    ) -> PublicSearchObservation:
        if platform is Platform.DOUYIN:
            path = "/api/v1/douyin/search/fetch_video_search_v2"
            payload = self._request(
                path,
                method="POST",
                json_body={"keyword": keyword, "cursor": 0},
            )
            candidates = _first_list(payload.get("data"), "aweme_list", "items", "data")
            contract = "tikhub-douyin-search-v2-v1"
        else:
            path = "/api/v1/xiaohongshu/web_v3/fetch_search_notes"
            payload = self._request(path, {"keyword": keyword, "page": 1})
            candidates = _first_list(payload.get("data"), "notes", "items")
            contract = "tikhub-xiaohongshu-web-v3-search-v1"
        results = [
            post for item in candidates if (post := _normalized_post(item, platform))
        ]
        request_id = payload.get("request_id")
        return PublicSearchObservation(
            endpoint_contract=contract,
            provider_request_id=request_id if isinstance(request_id, str) else None,
            fetched_at=datetime.now(UTC),
            raw_response=payload,
            results=results[:20],
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

    def fetch_account_posts(
        self,
        *,
        platform: Platform,
        platform_account_id: str,
    ) -> PublicAccountObservation:
        posts = [
            {
                "content_id": f"{platform_account_id}-1",
                "public_url": f"https://example.com/{platform.value}/mock-1",
                "title": "常规内容 A",
                "published_at": 1_785_715_200,
                "views": 900,
                "likes": 45,
                "comments": 6,
                "favorites": 12,
                "shares": 3,
            },
            {
                "content_id": f"{platform_account_id}-2",
                "public_url": f"https://example.com/{platform.value}/mock-2",
                "title": "常规内容 B",
                "published_at": 1_785_801_600,
                "views": 1200,
                "likes": 61,
                "comments": 8,
                "favorites": 15,
                "shares": 5,
            },
            {
                "content_id": f"{platform_account_id}-3",
                "public_url": f"https://example.com/{platform.value}/mock-3",
                "title": "高互动内容：运营提效实测",
                "published_at": 1_785_888_000,
                "views": 12600,
                "likes": 980,
                "comments": 126,
                "favorites": 340,
                "shares": 88,
            },
        ]
        return PublicAccountObservation(
            endpoint_contract=f"mock-{platform.value}-account-posts-v1",
            provider_request_id="mock-account-posts",
            fetched_at=datetime.now(UTC),
            raw_response={
                "code": 200,
                "data": {"account_id": platform_account_id, "posts": posts},
            },
            follower_count=12500,
            posts=posts,
        )

    def fetch_content_comments(
        self,
        *,
        platform: Platform,
        locator: dict[str, str],
    ) -> PublicCommentObservation:
        comments = [
            "这个工具多少钱，在哪里可以买？",
            "能不能出一期从下载安装到使用的教程？",
            "和同类产品相比有什么区别？",
            "实际使用会不会很复杂？",
            "希望增加批量导入功能。",
            "已经试过了，节省时间很明显。",
        ]
        return PublicCommentObservation(
            endpoint_contract=f"mock-{platform.value}-comments-v1",
            provider_request_id="mock-comments",
            fetched_at=datetime.now(UTC),
            raw_response={
                "code": 200,
                "data": {
                    "content_id": locator["content_id"],
                    "comments": [{"text": item} for item in comments],
                },
            },
            comments=comments,
        )

    def search_public_content(
        self,
        *,
        platform: Platform,
        keyword: str,
    ) -> PublicSearchObservation:
        results = [
            {
                "content_id": f"mock-search-{index}",
                "public_url": f"https://example.com/{platform.value}/search-{index}",
                "title": f"{keyword}：公开内容示例 {index}",
                "published_at": 1_785_888_000 + index,
                "views": 1000 * index,
                "likes": 80 * index,
                "comments": 10 * index,
                "favorites": 25 * index,
                "shares": 5 * index,
            }
            for index in range(1, 4)
        ]
        return PublicSearchObservation(
            endpoint_contract=f"mock-{platform.value}-search-v1",
            provider_request_id="mock-search",
            fetched_at=datetime.now(UTC),
            raw_response={"code": 200, "data": {"keyword": keyword, "items": results}},
            results=results,
        )
