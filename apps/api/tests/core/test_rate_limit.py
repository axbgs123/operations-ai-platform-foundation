from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from app.core.rate_limit import (
    InMemoryAtomicBackend,
    RateLimitBackendUnavailable,
    RateLimitCategory,
    RateLimitExceeded,
    RateLimitPolicy,
    RateLimiter,
    RedisAtomicBackend,
    build_authenticated_subject,
    build_subject_key,
    category_for_request,
    resolve_client_source,
    should_skip_rate_limit,
)


pytestmark = pytest.mark.security


def test_atomic_backend_never_overshoots_under_concurrency() -> None:
    limiter = RateLimiter(
        InMemoryAtomicBackend(),
        policies={
            RateLimitCategory.AI: RateLimitPolicy(
                limit=10,
                window=timedelta(minutes=1),
                count_failures=True,
                fail_closed=True,
            )
        },
    )

    def attempt() -> bool:
        try:
            limiter.check(RateLimitCategory.AI, "workspace:a:member:b")
            return True
        except RateLimitExceeded:
            return False

    with ThreadPoolExecutor(max_workers=20) as pool:
        outcomes = list(pool.map(lambda _: attempt(), range(40)))

    assert sum(outcomes) == 10


def test_categories_workspaces_and_demo_limits_are_independent() -> None:
    policies = {
        RateLimitCategory.AUTH: RateLimitPolicy(1, timedelta(minutes=1), True, True),
        RateLimitCategory.AI: RateLimitPolicy(2, timedelta(minutes=1), True, True),
    }
    limiter = RateLimiter(InMemoryAtomicBackend(), policies=policies, demo_factor=0.5)

    limiter.check(RateLimitCategory.AUTH, "workspace:a:member:m")
    limiter.check(RateLimitCategory.AI, "workspace:a:member:m")
    limiter.check(RateLimitCategory.AI, "workspace:b:member:m")
    with pytest.raises(RateLimitExceeded):
        limiter.check(RateLimitCategory.AUTH, "workspace:a:member:m")
    limiter.check(RateLimitCategory.AI, "workspace:a:member:m", demo=True)
    with pytest.raises(RateLimitExceeded):
        limiter.check(RateLimitCategory.AI, "workspace:a:member:m", demo=True)


def test_redis_failure_is_fail_closed_for_sensitive_and_bounded_for_read() -> None:
    class BrokenBackend:
        def increment(self, key: str, *, limit: int, window_seconds: int):
            raise ConnectionError("redis unavailable")

    limiter = RateLimiter(BrokenBackend())
    with pytest.raises(RateLimitBackendUnavailable):
        limiter.check(RateLimitCategory.AUTH, "source:trusted")
    with pytest.raises(RateLimitBackendUnavailable):
        limiter.check(RateLimitCategory.EXPORT, "workspace:a:member:b")

    for _ in range(5):
        limiter.check(RateLimitCategory.READ, "source:trusted")
    with pytest.raises(RateLimitExceeded):
        limiter.check(RateLimitCategory.READ, "source:trusted")


def test_untrusted_forwarded_for_is_ignored_and_subject_never_contains_secrets() -> (
    None
):
    assert (
        resolve_client_source(
            peer_ip="203.0.113.8",
            forwarded_for="198.51.100.1",
            trusted_proxies=frozenset(),
        )
        == "203.0.113.8"
    )
    assert (
        resolve_client_source(
            peer_ip="10.0.0.2",
            forwarded_for="198.51.100.1, 10.0.0.3",
            trusted_proxies=frozenset({"10.0.0.2"}),
        )
        == "198.51.100.1"
    )
    key = build_subject_key(
        category=RateLimitCategory.AUTH,
        source="invite.secret.token",
    )
    assert "invite.secret.token" not in key


def test_redis_backend_uses_atomic_lua_script() -> None:
    calls: list[tuple[str, int, tuple[object, ...]]] = []

    class FakeRedis:
        def eval(self, script: str, keys: int, *args: object):
            calls.append((script, keys, args))
            return [1, 60]

    decision = RedisAtomicBackend(FakeRedis()).increment(
        "safe-key",
        limit=3,
        window_seconds=60,
    )

    assert decision.allowed
    assert calls[0][1] == 1
    assert "INCR" in calls[0][0]
    assert "EXPIRE" in calls[0][0]


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("POST", "/v1/sessions/invite", RateLimitCategory.AUTH),
        ("POST", "/v1/sessions/current/resume", RateLimitCategory.AUTH),
        ("POST", "/v1/workspaces/onboard", RateLimitCategory.AUTH),
        ("POST", "/v1/contents/abc/analysis-runs", RateLimitCategory.AI),
        ("POST", "/v1/workspaces/a/risk-scans", RateLimitCategory.AI),
        ("POST", "/v1/imports/screenshot/recognitions", RateLimitCategory.UPLOAD),
        ("POST", "/v1/imports/tabular/preview", RateLimitCategory.UPLOAD),
        ("POST", "/v1/workspaces/a/restore-previews", RateLimitCategory.EXPORT),
        ("POST", "/v1/workspaces/a/zip-restores", RateLimitCategory.EXPORT),
        (
            "POST",
            "/v1/workspaces/a/deletion-confirmations",
            RateLimitCategory.DESTRUCTIVE,
        ),
    ],
)
def test_required_mutation_routes_have_explicit_categories(
    method: str,
    path: str,
    expected: RateLimitCategory,
) -> None:
    assert category_for_request(method, path) is expected


def test_authenticated_subject_is_workspace_and_member_scoped_without_secrets() -> None:
    subject = build_authenticated_subject("workspace-a", "member-b")
    assert subject == "workspace:workspace-a:member:member-b"
    key = build_subject_key(category=RateLimitCategory.AI, source=subject)
    assert "workspace-a" not in key
    assert "member-b" not in key


def test_no_cookie_resume_probe_skips_shared_ip_quota_but_session_rotation_does_not() -> None:
    path = "/v1/sessions/current/resume"
    assert should_skip_rate_limit(path, {})
    assert should_skip_rate_limit(path, {"cookie": "theme=light"})
    assert not should_skip_rate_limit(
        path,
        {"cookie": "session=synthetic-session-value"},
    )
    assert not should_skip_rate_limit("/v1/sessions/invite", {})
