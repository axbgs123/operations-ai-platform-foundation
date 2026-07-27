from __future__ import annotations

import hashlib
import math
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from http.cookies import SimpleCookie
from typing import Any, Protocol

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import get_settings


class RateLimitCategory(StrEnum):
    AUTH = "auth"
    AI = "ai"
    UPLOAD = "upload"
    EXPORT = "export"
    DESTRUCTIVE = "destructive"
    READ = "read"


@dataclass(frozen=True)
class RateLimitPolicy:
    limit: int
    window: timedelta
    count_failures: bool
    fail_closed: bool


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int
    count: int


class AtomicRateLimitBackend(Protocol):
    def increment(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision: ...


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("RATE_LIMITED")
        self.retry_after = max(1, retry_after)


class RateLimitBackendUnavailable(Exception):
    pass


DEFAULT_POLICIES = {
    RateLimitCategory.AUTH: RateLimitPolicy(10, timedelta(minutes=1), True, True),
    RateLimitCategory.AI: RateLimitPolicy(20, timedelta(minutes=1), True, True),
    RateLimitCategory.UPLOAD: RateLimitPolicy(30, timedelta(minutes=1), True, True),
    RateLimitCategory.EXPORT: RateLimitPolicy(10, timedelta(minutes=5), True, True),
    RateLimitCategory.DESTRUCTIVE: RateLimitPolicy(
        5,
        timedelta(minutes=10),
        True,
        True,
    ),
    RateLimitCategory.READ: RateLimitPolicy(120, timedelta(minutes=1), False, False),
}


class InMemoryAtomicBackend:
    def __init__(self, *, clock=time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._values: dict[str, tuple[int, float]] = {}

    def increment(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        with self._lock:
            now = self._clock()
            count, expires = self._values.get(
                key,
                (0, now + window_seconds),
            )
            if expires <= now:
                count, expires = 0, now + window_seconds
            count += 1
            self._values[key] = (count, expires)
            return RateLimitDecision(
                allowed=count <= limit,
                retry_after=max(1, math.ceil(expires - now)),
                count=count,
            )


class RedisAtomicBackend:
    LUA = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
""".strip()

    def __init__(self, client: Any) -> None:
        self._client = client

    def increment(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        result = self._client.eval(self.LUA, 1, key, window_seconds)
        count, ttl = int(result[0]), int(result[1])
        return RateLimitDecision(
            allowed=count <= limit,
            retry_after=max(1, ttl),
            count=count,
        )


class RateLimiter:
    def __init__(
        self,
        backend: AtomicRateLimitBackend,
        *,
        policies: dict[RateLimitCategory, RateLimitPolicy] | None = None,
        demo_factor: float = 0.25,
        local_fallback_limit: int = 5,
    ) -> None:
        self._backend = backend
        self._policies = {**DEFAULT_POLICIES, **(policies or {})}
        self._demo_factor = demo_factor
        self._fallback = InMemoryAtomicBackend()
        self._local_fallback_limit = local_fallback_limit

    def check(
        self,
        category: RateLimitCategory,
        subject: str,
        *,
        demo: bool = False,
    ) -> RateLimitDecision:
        policy = self._policies[category]
        limit = (
            max(1, math.floor(policy.limit * self._demo_factor))
            if demo
            else policy.limit
        )
        window_seconds = max(1, int(policy.window.total_seconds()))
        key = build_subject_key(category=category, source=subject, demo=demo)
        try:
            decision = self._backend.increment(
                key,
                limit=limit,
                window_seconds=window_seconds,
            )
        except Exception as error:
            if policy.fail_closed:
                raise RateLimitBackendUnavailable(
                    "RATE_LIMIT_BACKEND_UNAVAILABLE"
                ) from error
            decision = self._fallback.increment(
                key,
                limit=self._local_fallback_limit,
                window_seconds=window_seconds,
            )
        if not decision.allowed:
            raise RateLimitExceeded(decision.retry_after)
        return decision


def resolve_client_source(
    *,
    peer_ip: str,
    forwarded_for: str | None,
    trusted_proxies: frozenset[str],
) -> str:
    if peer_ip not in trusted_proxies or not forwarded_for:
        return peer_ip
    return forwarded_for.split(",", 1)[0].strip() or peer_ip


def build_subject_key(
    *,
    category: RateLimitCategory,
    source: str,
    demo: bool = False,
) -> str:
    digest = hashlib.sha256(source.encode()).hexdigest()
    mode = "demo" if demo else "standard"
    return f"operations-ai:rate:{category.value}:{mode}:{digest}"


def category_for_request(method: str, path: str) -> RateLimitCategory | None:
    normalized = path.lower()
    if normalized in {"/v1/sessions/invite"} or "/extension/bind" in normalized:
        return RateLimitCategory.AUTH
    if (
        any(
            marker in normalized
            for marker in ("/analysis", "/generation", "/risk-scans")
        )
        and method != "GET"
    ):
        return RateLimitCategory.AI
    if (
        any(
            marker in normalized
            for marker in (
                "/upload",
                "/capture",
                "/screenshot",
                "/imports/tabular",
            )
        )
        and method != "GET"
    ):
        return RateLimitCategory.UPLOAD
    if (
        any(
            marker in normalized
            for marker in ("/export", "/backup", "/restore", "restores")
        )
        and method != "GET"
    ):
        return RateLimitCategory.EXPORT
    if (
        any(marker in normalized for marker in ("/deletion", "/trash"))
        and method != "GET"
    ):
        return RateLimitCategory.DESTRUCTIVE
    return None


def default_rate_limiter() -> RateLimiter:
    settings = get_settings()
    if settings.app_mock_mode:
        return RateLimiter(
            InMemoryAtomicBackend(),
            policies={
                category: RateLimitPolicy(
                    limit=10_000,
                    window=policy.window,
                    count_failures=policy.count_failures,
                    fail_closed=policy.fail_closed,
                )
                for category, policy in DEFAULT_POLICIES.items()
            },
        )
    from redis import Redis

    configured = {
        RateLimitCategory.AUTH: RateLimitPolicy(
            settings.rate_limit_auth_per_minute,
            timedelta(minutes=1),
            True,
            True,
        ),
        RateLimitCategory.AI: RateLimitPolicy(
            settings.rate_limit_ai_per_minute,
            timedelta(minutes=1),
            True,
            True,
        ),
        RateLimitCategory.UPLOAD: RateLimitPolicy(
            settings.rate_limit_upload_per_minute,
            timedelta(minutes=1),
            True,
            True,
        ),
        RateLimitCategory.EXPORT: RateLimitPolicy(
            settings.rate_limit_export_per_five_minutes,
            timedelta(minutes=5),
            True,
            True,
        ),
        RateLimitCategory.DESTRUCTIVE: RateLimitPolicy(
            settings.rate_limit_destructive_per_ten_minutes,
            timedelta(minutes=10),
            True,
            True,
        ),
    }
    return RateLimiter(
        RedisAtomicBackend(Redis.from_url(settings.redis_url)),
        policies=configured,
        demo_factor=settings.rate_limit_demo_factor,
    )


def build_authenticated_subject(workspace_id: object, member_id: object) -> str:
    return f"workspace:{workspace_id}:member:{member_id}"


def _trusted_authenticated_subject(
    headers: dict[str, str],
    *,
    fallback: str,
) -> str:
    settings = get_settings()
    if settings.app_mock_mode:
        return fallback
    try:
        from app.core.database import SessionFactory
        from app.modules.imports.extension_auth import ExtensionTokenService
        from app.modules.workspace.auth import InviteAuthService

        cookie = SimpleCookie()
        cookie.load(headers.get("cookie", ""))
        session_token = cookie["session"].value if "session" in cookie else None
        authorization = headers.get("authorization", "")
        bearer = (
            authorization.split(None, 1)[1]
            if authorization.lower().startswith("bearer ")
            and len(authorization.split(None, 1)) == 2
            else None
        )
        with SessionFactory() as session:
            context = (
                InviteAuthService(session).authenticate(session_token)
                if session_token
                else None
            )
            if context is None and bearer:
                extension = ExtensionTokenService(session).authenticate(bearer)
                context = extension.context if extension is not None else None
        if context is not None and context.member_id is not None:
            return build_authenticated_subject(
                context.workspace_id,
                context.member_id,
            )
    except Exception:
        return fallback
    return fallback


class RateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: RateLimiter | None = None,
    ) -> None:
        self.app = app
        self._limiter = limiter or default_rate_limiter()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "GET").upper()
        path = scope.get("path", "")
        category = category_for_request(method, path)
        if category is None:
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", ())
        }
        peer_ip = scope.get("client", ("unknown", 0))[0]
        settings = get_settings()
        trusted_proxies = frozenset(
            value.strip()
            for value in settings.trusted_proxy_ips.split(",")
            if value.strip()
        )
        source = resolve_client_source(
            peer_ip=peer_ip,
            forwarded_for=headers.get("x-forwarded-for"),
            trusted_proxies=trusted_proxies,
        )
        subject = _trusted_authenticated_subject(headers, fallback=source)
        try:
            self._limiter.check(
                category,
                subject,
                demo=path.startswith("/v1/demo"),
            )
        except RateLimitExceeded as error:
            from app.core.logging import technical_metrics

            technical_metrics.record(
                "rate_limit_rejections_total",
                labels={"category": category.value},
            )
            response = JSONResponse(
                status_code=429,
                content={
                    "detail": {
                        "code": "RATE_LIMITED",
                        "message": "request limit reached",
                    }
                },
                headers={"Retry-After": str(error.retry_after)},
            )
            await response(scope, receive, send)
            return
        except RateLimitBackendUnavailable:
            response = JSONResponse(
                status_code=503,
                content={
                    "detail": {
                        "code": "RATE_LIMIT_BACKEND_UNAVAILABLE",
                        "message": "request protection is temporarily unavailable",
                    }
                },
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
