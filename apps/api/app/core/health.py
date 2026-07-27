from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Callable, Literal

from redis import Redis
from sqlalchemy import text

from app.core.config import get_settings
from sqlalchemy import create_engine
from app.core.storage import S3Storage


DependencyName = Literal["postgresql", "redis", "s3"]


@dataclass(frozen=True)
class DependencyStatus:
    name: DependencyName
    status: Literal["ready", "not_ready"]
    error_code: str | None = None


@dataclass(frozen=True)
class ReadinessResult:
    status: Literal["ready", "not_ready"]
    components: tuple[DependencyStatus, ...]


class ReadinessService:
    def __init__(
        self,
        checks: dict[DependencyName, Callable[[], None]],
        *,
        timeout_seconds: float,
    ) -> None:
        self._checks = checks
        self._timeout_seconds = timeout_seconds

    def check(self) -> ReadinessResult:
        results: list[DependencyStatus] = []
        pool = ThreadPoolExecutor(max_workers=len(self._checks))
        try:
            futures = {name: pool.submit(check) for name, check in self._checks.items()}
            for name in ("postgresql", "redis", "s3"):
                future = futures[name]
                try:
                    future.result(timeout=self._timeout_seconds)
                except FutureTimeout:
                    results.append(
                        DependencyStatus(
                            name=name,
                            status="not_ready",
                            error_code="DEPENDENCY_TIMEOUT",
                        )
                    )
                except Exception:
                    results.append(
                        DependencyStatus(
                            name=name,
                            status="not_ready",
                            error_code="DEPENDENCY_UNAVAILABLE",
                        )
                    )
                else:
                    results.append(DependencyStatus(name=name, status="ready"))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        from app.core.observability import technical_metrics

        for component in results:
            technical_metrics.record(
                "readiness",
                labels={
                    "component": component.name,
                    "status": component.status,
                },
            )
        return ReadinessResult(
            status=(
                "ready"
                if all(item.status == "ready" for item in results)
                else "not_ready"
            ),
            components=tuple(results),
        )


def _check_postgres() -> None:
    settings = get_settings()
    engine = create_engine(
        settings.database_url,
        connect_args={
            "connect_timeout": max(
                1,
                math.ceil(settings.readiness_timeout_seconds),
            )
        },
        pool_pre_ping=False,
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()


def _check_redis() -> None:
    settings = get_settings()
    if not Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=settings.readiness_timeout_seconds,
        socket_timeout=settings.readiness_timeout_seconds,
    ).ping():
        raise ConnectionError("redis ping failed")


def _check_s3() -> None:
    S3Storage().check_ready()


def get_readiness_service() -> ReadinessService:
    settings = get_settings()
    return ReadinessService(
        {
            "postgresql": _check_postgres,
            "redis": _check_redis,
            "s3": _check_s3,
        },
        timeout_seconds=settings.readiness_timeout_seconds,
    )
