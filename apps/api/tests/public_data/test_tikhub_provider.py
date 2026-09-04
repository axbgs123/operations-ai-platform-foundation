from datetime import UTC, datetime

import httpx
import pytest

from app.modules.content.account_models import Platform
from app.modules.public_data.contracts import PublicProviderError
from app.modules.public_data.providers import TikHubProvider


def test_tikhub_douyin_resolution_and_metric_normalization() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        if request.url.path.endswith("fetch_one_video_by_share_url"):
            return httpx.Response(
                200, json={"code": 200, "data": {"aweme_id": "730001"}}
            )
        return httpx.Response(
            200,
            json={
                "code": 200,
                "request_id": "req-1",
                "data": {
                    "statistics": {
                        "play_count": "1,200",
                        "digg_count": 128,
                        "comment_count": 18,
                        "collect_count": 36,
                        "share_count": 12,
                    }
                },
            },
        )

    provider = TikHubProvider(
        api_key="test-key",
        endpoint_region="china",
        transport=httpx.MockTransport(handler),
    )
    resolved = provider.resolve_content(
        platform=Platform.DOUYIN,
        public_url="https://www.douyin.com/video/730001",
    )
    result = provider.fetch_content_metrics(
        platform=Platform.DOUYIN,
        locator=resolved.locator,
    )

    assert resolved.platform_content_id == "730001"
    assert result.metrics == {
        "views": 1200,
        "likes": 128,
        "comments": 18,
        "favorites": 36,
        "shares": 12,
    }
    assert result.provider_request_id == "req-1"
    assert result.fetched_at <= datetime.now(UTC)


def test_tikhub_xiaohongshu_preserves_required_locator() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("get_note_id_and_xsec_token"):
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": {"note_id": "note-123", "xsec_token": "xsec-abc"},
                },
            )
        assert request.url.params["note_id"] == "note-123"
        assert request.url.params["xsec_token"] == "xsec-abc"
        return httpx.Response(
            200,
            json={
                "code": 200,
                "data": {
                    "interact_info": {
                        "liked_count": "88",
                        "comment_count": "9",
                        "collected_count": "27",
                        "share_count": "3",
                    }
                },
            },
        )

    provider = TikHubProvider(
        api_key="test-key",
        endpoint_region="global",
        transport=httpx.MockTransport(handler),
    )
    resolved = provider.resolve_content(
        platform=Platform.XIAOHONGSHU,
        public_url="https://www.xiaohongshu.com/explore/note-123",
    )
    result = provider.fetch_content_metrics(
        platform=Platform.XIAOHONGSHU,
        locator=resolved.locator,
    )

    assert resolved.locator == {"content_id": "note-123", "xsec_token": "xsec-abc"}
    assert result.metrics["likes"] == 88
    assert result.metrics["favorites"] == 27
    assert result.metrics["views"] is None


def test_tikhub_maps_rate_limits_to_retryable_error() -> None:
    provider = TikHubProvider(
        api_key="test-key",
        endpoint_region="china",
        transport=httpx.MockTransport(lambda request: httpx.Response(429)),
    )

    with pytest.raises(PublicProviderError) as captured:
        provider.test_connection()

    assert captured.value.code == "PUBLIC_PROVIDER_RATE_LIMITED"
    assert captured.value.retryable is True


def test_tikhub_collects_competitor_posts_and_comments() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("fetch_video_search_v2"):
            assert request.method == "POST"
            assert b'"keyword":"AI"' in request.content
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "request_id": "search-1",
                    "data": {
                        "items": [
                            {
                                "aweme_id": "search-video-1",
                                "desc": "AI 热点",
                                "statistics": {"digg_count": 300},
                            }
                        ]
                    },
                },
            )
        if request.url.path.endswith("fetch_user_post_videos"):
            assert request.url.params["sec_user_id"] == "sec-user-1"
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "request_id": "posts-1",
                    "data": {
                        "aweme_list": [
                            {
                                "aweme_id": "video-1",
                                "desc": "运营提效实测",
                                "statistics": {
                                    "play_count": 2000,
                                    "digg_count": 180,
                                    "comment_count": 20,
                                    "collect_count": 45,
                                    "share_count": 9,
                                },
                            }
                        ]
                    },
                },
            )
        assert request.url.path.endswith("fetch_video_comments")
        assert request.url.params["aweme_id"] == "video-1"
        return httpx.Response(
            200,
            json={
                "code": 200,
                "request_id": "comments-1",
                "data": {"comments": [{"text": "这个怎么使用？"}]},
            },
        )

    provider = TikHubProvider(
        api_key="test-key",
        endpoint_region="global",
        transport=httpx.MockTransport(handler),
    )

    posts = provider.fetch_account_posts(
        platform=Platform.DOUYIN,
        platform_account_id="sec-user-1",
    )
    comments = provider.fetch_content_comments(
        platform=Platform.DOUYIN,
        locator={"content_id": "video-1"},
    )
    search = provider.search_public_content(
        platform=Platform.DOUYIN,
        keyword="AI",
    )

    assert posts.provider_request_id == "posts-1"
    assert posts.posts[0]["likes"] == 180
    assert comments.provider_request_id == "comments-1"
    assert comments.comments == ["这个怎么使用？"]
    assert search.provider_request_id == "search-1"
    assert search.results[0]["title"] == "AI 热点"
