from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import re
import secrets
import threading
import time
from typing import Callable, Literal, Protocol, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import WorkspaceContext
from app.modules.models.capabilities import Capability
from app.modules.models.catalog import get_catalog_entry
from app.modules.models.config_service import model_configuration_version
from app.modules.models.models import (
    ModelConfig,
    ModelContractValidationRun,
    ModelUsageAttempt,
    ModelUsageAttemptStatus,
    ModelUsagePolicy,
    ModelUsageReservation,
    ModelUsageReservationStatus,
    ModelValidationResult,
)
from app.modules.workspace.permissions import Permission, require_permission


PRICING_VERSION = "aliyun-public-2026-07-29-v1"
VALIDATION_SUITE_VERSION = "qianwen-controlled-contract-v1"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ProviderOperation(StrEnum):
    TEXT_GENERATION = "text_generation"
    ANALYSIS = "analysis"
    OCR = "ocr"
    EMBEDDING_REBUILD = "embedding_rebuild"
    EMBEDDING_QUERY = "embedding_query"
    COVER_TEXT_TO_IMAGE = "cover_text_to_image"
    COVER_IMAGE_EDIT = "cover_image_edit"


ReservationStatus = ModelUsageReservationStatus
UsageAttemptOutcome = ModelUsageAttemptStatus
ValidationResult = ModelValidationResult


class UsageGovernanceError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class UsageEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    embedding_tokens: int = Field(default=0, ge=0)
    ocr_images: int = Field(default=0, ge=0)
    generated_images: int = Field(default=0, ge=0)
    input_images: int = Field(default=0, ge=0)
    output_images: int = Field(default=0, ge=0)


class PolicyLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_concurrent_calls: int
    max_calls_per_minute: int
    daily_request_limit: int
    daily_input_token_limit: int
    daily_output_token_limit: int
    daily_embedding_token_limit: int
    daily_ocr_image_limit: int
    daily_generated_image_limit: int
    daily_cost_limit_microunits: int


HARD_POLICY_LIMITS = PolicyLimits(
    max_concurrent_calls=8,
    max_calls_per_minute=600,
    daily_request_limit=10_000,
    daily_input_token_limit=100_000_000,
    daily_output_token_limit=20_000_000,
    daily_embedding_token_limit=100_000_000,
    daily_ocr_image_limit=10_000,
    daily_generated_image_limit=1_000,
    daily_cost_limit_microunits=100_000_000,
)


class ModelUsagePolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: Capability
    enabled: bool
    max_concurrent_calls: int = Field(ge=0)
    max_calls_per_minute: int = Field(ge=0)
    daily_request_limit: int = Field(ge=0)
    daily_input_token_limit: int = Field(ge=0)
    daily_output_token_limit: int = Field(ge=0)
    daily_embedding_token_limit: int = Field(ge=0)
    daily_ocr_image_limit: int = Field(ge=0)
    daily_generated_image_limit: int = Field(ge=0)
    daily_cost_limit_microunits: int = Field(ge=0)
    currency: Literal["CNY"]


class ControlledValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_config_id: UUID
    region: Literal["cn-beijing", "ap-southeast-1"]
    capability: Capability
    model_id: str = Field(min_length=1, max_length=160)
    max_calls: int = Field(ge=1, le=5)
    max_input_tokens: int = Field(ge=0, le=10_000)
    max_output_tokens: int = Field(ge=0, le=5_000)
    max_images: int = Field(ge=0, le=2)
    max_cost_microunits: int = Field(ge=1, le=1_000_000)
    confirm_real_call: bool

    @model_validator(mode="after")
    def require_confirmation(self) -> ControlledValidationRequest:
        if not self.confirm_real_call:
            raise ValueError("confirm_real_call must be true")
        return self


@dataclass(frozen=True)
class _Price:
    input_per_million: int = 0
    output_per_million: int = 0
    embedding_per_million: int = 0
    generated_image: int = 0


_PRICES: dict[tuple[str, str], _Price] = {
    (
        "qwen3.5-plus-2026-04-20",
        "cn-beijing",
    ): _Price(input_per_million=800_000, output_per_million=4_800_000),
    (
        "qwen3.5-plus-2026-04-20",
        "ap-southeast-1",
    ): _Price(input_per_million=2_936_000, output_per_million=17_614_000),
    (
        "qwen-vl-ocr-2025-11-20",
        "cn-beijing",
    ): _Price(input_per_million=300_000, output_per_million=500_000),
    (
        "qwen-vl-ocr-2025-11-20",
        "ap-southeast-1",
    ): _Price(input_per_million=514_000, output_per_million=1_174_000),
    (
        "text-embedding-v4",
        "cn-beijing",
    ): _Price(embedding_per_million=500_000),
    (
        "text-embedding-v4",
        "ap-southeast-1",
    ): _Price(embedding_per_million=734_000),
    (
        "qwen-image-2.0-pro-2026-06-22",
        "cn-beijing",
    ): _Price(generated_image=500_000),
    (
        "qwen-image-2.0-pro-2026-06-22",
        "ap-southeast-1",
    ): _Price(generated_image=550_443),
}


def _scaled_cost(units: int, price_per_million: int) -> int:
    if units == 0 or price_per_million == 0:
        return 0
    return (units * price_per_million + 999_999) // 1_000_000


def estimate_cost_microunits(
    *,
    model_id: str,
    region: str,
    estimate: UsageEstimate,
) -> int:
    try:
        price = _PRICES[(model_id, region)]
    except KeyError as error:
        raise UsageGovernanceError("MODEL_PRICING_UNAVAILABLE") from error
    return (
        _scaled_cost(estimate.input_tokens, price.input_per_million)
        + _scaled_cost(estimate.output_tokens, price.output_per_million)
        + _scaled_cost(
            estimate.embedding_tokens,
            price.embedding_per_million,
        )
        + estimate.generated_images * price.generated_image
    )


def create_model_usage_governor(
    *,
    session_factory: sessionmaker[Session],
    redis_url: str,
    workspace_id: UUID,
    model_config: ModelConfig,
    actor_id: UUID | None,
    task_id: UUID,
    capability: Capability,
    operation: ProviderOperation,
    contract_version: str,
    configuration_version: str,
) -> ModelUsageGovernor:
    from redis import Redis

    if model_config.region is None:
        raise UsageGovernanceError("MODEL_CONFIGURATION_REQUIRED")
    return ModelUsageGovernor(
        session_factory=session_factory,
        workspace_id=workspace_id,
        model_config_id=model_config.id,
        actor_id=actor_id or UUID(int=0),
        task_id=task_id,
        provider=model_config.provider,
        model_id=model_config.model_id,
        region=model_config.region,
        capability=capability,
        operation=operation,
        contract_version=contract_version,
        configuration_version=configuration_version,
        lease_backend=RedisUsageLeaseBackend(
            cast(
                RedisEvalClient,
                Redis.from_url(redis_url, decode_responses=True),
            )
        ),
    )


class ModelUsagePolicyService:
    def __init__(
        self,
        session: Session,
        context: WorkspaceContext,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session = session
        self._context = context
        self._clock = clock

    def save(self, data: ModelUsagePolicyInput) -> ModelUsagePolicy:
        require_permission(self._context.role, Permission.MANAGE_MODELS)
        now = _aware(self._clock())
        for name in PolicyLimits.model_fields:
            if getattr(data, name) > getattr(HARD_POLICY_LIMITS, name):
                raise ValueError(f"{name} exceeds server hard limit")
        latest = self._session.scalar(
            select(ModelUsagePolicy)
            .where(
                ModelUsagePolicy.workspace_id == self._context.workspace_id,
                ModelUsagePolicy.capability == data.capability.value,
            )
            .order_by(ModelUsagePolicy.version.desc())
            .limit(1)
        )
        policy = ModelUsagePolicy(
            workspace_id=self._context.workspace_id,
            capability=data.capability.value,
            enabled=data.enabled,
            max_concurrent_calls=data.max_concurrent_calls,
            max_calls_per_minute=data.max_calls_per_minute,
            daily_request_limit=data.daily_request_limit,
            daily_input_token_limit=data.daily_input_token_limit,
            daily_output_token_limit=data.daily_output_token_limit,
            daily_embedding_token_limit=data.daily_embedding_token_limit,
            daily_ocr_image_limit=data.daily_ocr_image_limit,
            daily_generated_image_limit=data.daily_generated_image_limit,
            daily_cost_limit_microunits=data.daily_cost_limit_microunits,
            currency=data.currency,
            effective_from=now,
            version=(latest.version + 1 if latest is not None else 1),
            updated_by=_require_member(self._context),
        )
        self._session.add(policy)
        self._session.flush()
        return policy

    def current(self, capability: Capability) -> ModelUsagePolicy | None:
        require_permission(self._context.role, Permission.MANAGE_MODELS)
        return _current_policy(
            self._session,
            workspace_id=self._context.workspace_id,
            capability=capability,
            now=_aware(self._clock()),
        )


class UsageLeaseBackend(Protocol):
    def acquire(self, key: str, *, limit: int, ttl_seconds: int) -> str | None: ...

    def renew(self, key: str, token: str, *, ttl_seconds: int) -> bool: ...

    def release(self, key: str, token: str) -> bool: ...

    def check_rate(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> bool: ...


class RedisEvalClient(Protocol):
    def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: object,
    ) -> object: ...


class RedisUsageLeaseBackend:
    _ACQUIRE_SCRIPT = """
local key = KEYS[1]
local token = ARGV[1]
local limit = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
local now = redis.call('TIME')
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
redis.call('ZREMRANGEBYSCORE', key, '-inf', now_ms)
if redis.call('ZCARD', key) >= limit then
  return false
end
redis.call('ZADD', key, now_ms + ttl * 1000, token)
redis.call('EXPIRE', key, ttl)
return token
"""
    _RENEW_SCRIPT = """
local key = KEYS[1]
local token = ARGV[1]
local ttl = tonumber(ARGV[2])
local score = redis.call('ZSCORE', key, token)
if not score then
  return 0
end
local now = redis.call('TIME')
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
if tonumber(score) <= now_ms then
  redis.call('ZREM', key, token)
  return 0
end
redis.call('ZADD', key, now_ms + ttl * 1000, token)
redis.call('EXPIRE', key, ttl)
return 1
"""
    _RELEASE_SCRIPT = """
local key = KEYS[1]
local token = ARGV[1]
return redis.call('ZREM', key, token)
"""
    _RATE_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local count = redis.call('INCR', key)
if count == 1 then
  redis.call('EXPIRE', key, window)
end
if count > limit then
  return 0
end
return 1
"""

    def __init__(self, redis: RedisEvalClient) -> None:
        self._redis = redis

    def acquire(self, key: str, *, limit: int, ttl_seconds: int) -> str | None:
        if limit <= 0:
            return None
        token = secrets.token_urlsafe(24)
        result = self._redis.eval(
            self._ACQUIRE_SCRIPT,
            1,
            key,
            token,
            limit,
            ttl_seconds,
        )
        if result in (None, False, 0):
            return None
        if isinstance(result, bytes):
            return result.decode("utf-8")
        return str(result)

    def renew(self, key: str, token: str, *, ttl_seconds: int) -> bool:
        return bool(
            self._redis.eval(
                self._RENEW_SCRIPT,
                1,
                key,
                token,
                ttl_seconds,
            )
        )

    def release(self, key: str, token: str) -> bool:
        return bool(
            self._redis.eval(
                self._RELEASE_SCRIPT,
                1,
                key,
                token,
            )
        )

    def check_rate(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> bool:
        if limit <= 0:
            return False
        return bool(
            self._redis.eval(
                self._RATE_SCRIPT,
                1,
                key,
                limit,
                window_seconds,
            )
        )


class InMemoryUsageLeaseBackend:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._leases: dict[str, dict[str, float]] = {}
        self._rates: dict[str, tuple[int, float]] = {}

    def acquire(self, key: str, *, limit: int, ttl_seconds: int) -> str | None:
        if limit <= 0:
            return None
        with self._lock:
            now = self._clock()
            leases = self._leases.setdefault(key, {})
            self._leases[key] = {
                token: expiry
                for token, expiry in leases.items()
                if expiry > now
            }
            if len(self._leases[key]) >= limit:
                return None
            token = secrets.token_urlsafe(24)
            self._leases[key][token] = now + ttl_seconds
            return token

    def renew(self, key: str, token: str, *, ttl_seconds: int) -> bool:
        with self._lock:
            now = self._clock()
            expiry = self._leases.get(key, {}).get(token)
            if expiry is None or expiry <= now:
                return False
            self._leases[key][token] = now + ttl_seconds
            return True

    def release(self, key: str, token: str) -> bool:
        with self._lock:
            leases = self._leases.get(key)
            if leases is None or token not in leases:
                return False
            del leases[token]
            return True

    def check_rate(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> bool:
        if limit <= 0:
            return False
        with self._lock:
            now = self._clock()
            count, expiry = self._rates.get(key, (0, now + window_seconds))
            if expiry <= now:
                count, expiry = 0, now + window_seconds
            count += 1
            self._rates[key] = (count, expiry)
            return count <= limit


@dataclass(frozen=True)
class UsageAttemptHandle:
    analytics_eligible: bool
    reservation_id: UUID | None
    attempt_id: UUID
    lease_key: str | None
    lease_token: str | None
    estimate: UsageEstimate
    estimated_cost_microunits: int
    provider_attempt_number: int


class AttemptGovernor(Protocol):
    def begin_attempt(
        self,
        provider_attempt_number: int,
        estimate: UsageEstimate,
    ) -> UsageAttemptHandle: ...

    def finish_attempt(
        self,
        handle: UsageAttemptHandle,
        *,
        outcome: UsageAttemptOutcome,
        actual: UsageEstimate | None,
        latency_ms: int,
        provider_request_id: str | None = None,
        stable_error_code: str | None = None,
    ) -> None: ...


@contextmanager
def usage_lease_heartbeat(
    governor: AttemptGovernor | None,
    handle: UsageAttemptHandle | None,
) -> Iterator[None]:
    heartbeat = getattr(governor, "heartbeat", None)
    if handle is None or not callable(heartbeat):
        yield
        return
    with heartbeat(handle):
        yield


class ModelUsageGovernor:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        workspace_id: UUID,
        model_config_id: UUID,
        actor_id: UUID,
        task_id: UUID,
        provider: str,
        model_id: str,
        region: str,
        capability: Capability,
        operation: ProviderOperation,
        contract_version: str,
        configuration_version: str,
        lease_backend: UsageLeaseBackend,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        mock_mode: bool = False,
        lease_ttl_seconds: int = 60,
    ) -> None:
        self._factory = session_factory
        self._workspace_id = workspace_id
        self._model_config_id = model_config_id
        self._actor_id = actor_id
        self._task_id = task_id
        self._provider = provider
        self._model_id = model_id
        self._region = region
        self._capability = capability
        self._operation = operation
        self._contract_version = contract_version
        self._configuration_version = configuration_version
        self._lease_backend = lease_backend
        self._clock = clock
        self._mock_mode = mock_mode
        self._lease_ttl = lease_ttl_seconds

    def begin_attempt(
        self,
        provider_attempt_number: int,
        estimate: UsageEstimate,
    ) -> UsageAttemptHandle:
        attempt_id = uuid4()
        if self._mock_mode:
            return UsageAttemptHandle(
                analytics_eligible=False,
                reservation_id=None,
                attempt_id=attempt_id,
                lease_key=None,
                lease_token=None,
                estimate=estimate,
                estimated_cost_microunits=0,
                provider_attempt_number=provider_attempt_number,
            )
        now = _aware(self._clock())
        estimated_cost = estimate_cost_microunits(
            model_id=self._model_id,
            region=self._region,
            estimate=estimate,
        )
        with self._factory() as session:
            policy = _current_policy(
                session,
                workspace_id=self._workspace_id,
                capability=self._capability,
                now=now,
                for_update=True,
            )
            if policy is None or not policy.enabled:
                raise UsageGovernanceError("MODEL_USAGE_POLICY_REQUIRED")
            self._check_daily_limits(
                session,
                policy=policy,
                now=now,
                estimate=estimate,
                estimated_cost=estimated_cost,
            )
            reservation = ModelUsageReservation(
                workspace_id=self._workspace_id,
                model_config_id=self._model_config_id,
                actor_id=self._actor_id,
                task_id=self._task_id,
                attempt_id=attempt_id,
                provider_attempt_number=provider_attempt_number,
                provider=self._provider,
                model_id=self._model_id,
                region=self._region,
                capability=self._capability.value,
                operation=self._operation.value,
                contract_version=self._contract_version,
                configuration_version=self._configuration_version,
                policy_version=policy.version,
                pricing_version=PRICING_VERSION,
                estimated_usage=estimate.model_dump(),
                reserved_cost_microunits=estimated_cost,
                status=ModelUsageReservationStatus.RESERVED,
                expires_at=now + timedelta(minutes=15),
                operation_version=1,
                created_at=now,
                settled_at=None,
            )
            session.add(reservation)
            session.commit()
            reservation_id = reservation.id
            concurrent_limit = policy.max_concurrent_calls
            minute_limit = policy.max_calls_per_minute
        rate_key = (
            f"operations-ai:model-usage:rate:{self._workspace_id}:"
            f"{self._capability.value}"
        )
        lease_key = (
            f"operations-ai:model-usage:lease:{self._workspace_id}:"
            f"{self._capability.value}"
        )
        try:
            rate_allowed = self._lease_backend.check_rate(
                rate_key,
                limit=minute_limit,
                window_seconds=60,
            )
            lease_token = (
                self._lease_backend.acquire(
                    lease_key,
                    limit=concurrent_limit,
                    ttl_seconds=self._lease_ttl,
                )
                if rate_allowed
                else None
            )
        except Exception as error:
            self._release_reservation(reservation_id, now)
            raise UsageGovernanceError(
                "MODEL_USAGE_LIMIT_BACKEND_UNAVAILABLE"
            ) from error
        if lease_token is None:
            self._release_reservation(reservation_id, now)
            raise UsageGovernanceError("MODEL_USAGE_LIMIT_EXCEEDED")
        return UsageAttemptHandle(
            analytics_eligible=True,
            reservation_id=reservation_id,
            attempt_id=attempt_id,
            lease_key=lease_key,
            lease_token=lease_token,
            estimate=estimate,
            estimated_cost_microunits=estimated_cost,
            provider_attempt_number=provider_attempt_number,
        )

    def finish_attempt(
        self,
        handle: UsageAttemptHandle,
        *,
        outcome: UsageAttemptOutcome,
        actual: UsageEstimate | None,
        latency_ms: int,
        provider_request_id: str | None = None,
        stable_error_code: str | None = None,
    ) -> None:
        if not handle.analytics_eligible:
            return
        if handle.reservation_id is None:
            raise AssertionError("analytics-eligible attempt requires reservation")
        now = _aware(self._clock())
        safe_request_id = (
            provider_request_id
            if provider_request_id
            and _SAFE_REQUEST_ID.fullmatch(provider_request_id)
            else None
        )
        with self._factory() as session:
            reservation = session.get(
                ModelUsageReservation,
                handle.reservation_id,
            )
            if (
                reservation is None
                or reservation.workspace_id != self._workspace_id
                or reservation.status
                is not ModelUsageReservationStatus.RESERVED
            ):
                raise UsageGovernanceError("MODEL_USAGE_RESERVATION_STALE")
            duplicate = session.scalar(
                select(ModelUsageAttempt).where(
                    ModelUsageAttempt.reservation_id == reservation.id
                )
            )
            if duplicate is not None:
                raise UsageGovernanceError("MODEL_USAGE_ATTEMPT_EXISTS")
            settled_cost: int | None
            if outcome is UsageAttemptOutcome.SUCCEEDED:
                usage = actual or handle.estimate
                usage_basis = "settled" if actual is not None else "estimated"
                settled_cost = estimate_cost_microunits(
                    model_id=self._model_id,
                    region=self._region,
                    estimate=usage,
                )
                reservation.status = ModelUsageReservationStatus.SETTLED
            elif outcome is UsageAttemptOutcome.FAILED_UNBILLED:
                usage = UsageEstimate()
                usage_basis = "settled"
                settled_cost = 0
                reservation.status = ModelUsageReservationStatus.RELEASED
            else:
                usage = actual or UsageEstimate()
                usage_basis = "settled" if actual is not None else "unknown"
                settled_cost = (
                    estimate_cost_microunits(
                        model_id=self._model_id,
                        region=self._region,
                        estimate=usage,
                    )
                    if actual is not None
                    else None
                )
                reservation.status = ModelUsageReservationStatus.UNKNOWN
            reservation.settled_at = now
            session.add(
                ModelUsageAttempt(
                    workspace_id=self._workspace_id,
                    reservation_id=reservation.id,
                    task_id=self._task_id,
                    attempt_id=handle.attempt_id,
                    provider_attempt_number=handle.provider_attempt_number,
                    provider=self._provider,
                    model_id=self._model_id,
                    region=self._region,
                    capability=self._capability.value,
                    operation=self._operation.value,
                    contract_version=self._contract_version,
                    configuration_version=self._configuration_version,
                    pricing_version=PRICING_VERSION,
                    usage_basis=usage_basis,
                    status=ModelUsageAttemptStatus(outcome.value),
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    total_tokens=usage.input_tokens + usage.output_tokens,
                    image_inputs=usage.input_images + usage.ocr_images,
                    image_outputs=usage.output_images
                    + usage.generated_images,
                    embedding_inputs=usage.embedding_tokens,
                    estimated_cost_microunits=(
                        handle.estimated_cost_microunits
                    ),
                    settled_cost_microunits=settled_cost,
                    currency="CNY",
                    latency_ms=max(0, latency_ms),
                    provider_request_id=safe_request_id,
                    stable_error_code=stable_error_code,
                    created_at=now,
                )
            )
            session.commit()
        if handle.lease_key and handle.lease_token:
            self._lease_backend.release(
                handle.lease_key,
                handle.lease_token,
            )

    def renew(self, handle: UsageAttemptHandle) -> bool:
        if not handle.analytics_eligible:
            return True
        if not handle.lease_key or not handle.lease_token:
            return False
        return self._lease_backend.renew(
            handle.lease_key,
            handle.lease_token,
            ttl_seconds=self._lease_ttl,
        )

    @contextmanager
    def heartbeat(
        self,
        handle: UsageAttemptHandle,
        *,
        interval_seconds: float | None = None,
    ) -> Iterator[None]:
        if not handle.analytics_eligible:
            yield
            return
        stop = threading.Event()
        interval = interval_seconds or max(1.0, self._lease_ttl / 3)

        def renew_until_stopped() -> None:
            while not stop.wait(interval):
                try:
                    if not self.renew(handle):
                        return
                except Exception:
                    return

        thread = threading.Thread(
            target=renew_until_stopped,
            name="model-usage-lease-heartbeat",
            daemon=True,
        )
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=min(interval, 1.0))

    def _release_reservation(
        self,
        reservation_id: UUID,
        now: datetime,
    ) -> None:
        with self._factory() as session:
            reservation = session.get(ModelUsageReservation, reservation_id)
            if (
                reservation is not None
                and reservation.status
                is ModelUsageReservationStatus.RESERVED
            ):
                reservation.status = ModelUsageReservationStatus.RELEASED
                reservation.settled_at = now
                session.commit()

    def _check_daily_limits(
        self,
        session: Session,
        *,
        policy: ModelUsagePolicy,
        now: datetime,
        estimate: UsageEstimate,
        estimated_cost: int,
    ) -> None:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        rows = session.scalars(
            select(ModelUsageReservation).where(
                ModelUsageReservation.workspace_id == self._workspace_id,
                ModelUsageReservation.capability == self._capability.value,
                ModelUsageReservation.created_at >= start,
                ModelUsageReservation.status.in_(
                    (
                        ModelUsageReservationStatus.RESERVED,
                        ModelUsageReservationStatus.SETTLED,
                        ModelUsageReservationStatus.UNKNOWN,
                    )
                ),
            )
        ).all()
        totals = UsageEstimate(
            input_tokens=sum(
                int(row.estimated_usage.get("input_tokens", 0))
                for row in rows
            ),
            output_tokens=sum(
                int(row.estimated_usage.get("output_tokens", 0))
                for row in rows
            ),
            embedding_tokens=sum(
                int(row.estimated_usage.get("embedding_tokens", 0))
                for row in rows
            ),
            ocr_images=sum(
                int(row.estimated_usage.get("ocr_images", 0))
                for row in rows
            ),
            generated_images=sum(
                int(row.estimated_usage.get("generated_images", 0))
                for row in rows
            ),
        )
        checks = (
            (
                len(rows) + 1,
                policy.daily_request_limit,
            ),
            (
                totals.input_tokens + estimate.input_tokens,
                policy.daily_input_token_limit,
            ),
            (
                totals.output_tokens + estimate.output_tokens,
                policy.daily_output_token_limit,
            ),
            (
                totals.embedding_tokens + estimate.embedding_tokens,
                policy.daily_embedding_token_limit,
            ),
            (
                totals.ocr_images + estimate.ocr_images,
                policy.daily_ocr_image_limit,
            ),
            (
                totals.generated_images + estimate.generated_images,
                policy.daily_generated_image_limit,
            ),
            (
                sum(row.reserved_cost_microunits for row in rows)
                + estimated_cost,
                policy.daily_cost_limit_microunits,
            ),
        )
        if any(value > limit for value, limit in checks):
            raise UsageGovernanceError("MODEL_USAGE_BUDGET_EXCEEDED")


class ControlledValidationService:
    def __init__(
        self,
        session: Session,
        context: WorkspaceContext,
        *,
        real_calls_authorized: bool,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session = session
        self._context = context
        self._real_calls_authorized = real_calls_authorized
        self._clock = clock

    def create(
        self,
        request: ControlledValidationRequest,
    ) -> ModelContractValidationRun:
        require_permission(self._context.role, Permission.MANAGE_MODELS)
        now = _aware(self._clock())
        config = self._session.scalar(
            select(ModelConfig).where(
                ModelConfig.id == request.model_config_id,
                ModelConfig.workspace_id == self._context.workspace_id,
            )
        )
        if config is None:
            raise LookupError("model config not found")
        catalog = get_catalog_entry(config.provider, config.model_id)
        if (
            config.model_id != request.model_id
            or config.region != request.region
            or request.capability not in catalog.capabilities
        ):
            raise ValueError("validation target does not match model config")
        if self._real_calls_authorized:
            raise UsageGovernanceError(
                "CONTROLLED_VALIDATION_RUNNER_REQUIRED"
            )
        run = ModelContractValidationRun(
            workspace_id=self._context.workspace_id,
            model_config_id=config.id,
            region=request.region,
            capability=request.capability.value,
            model_id=request.model_id,
            contract_version=catalog.contract_version,
            configuration_version=model_configuration_version(config),
            validation_suite_version=VALIDATION_SUITE_VERSION,
            max_calls=request.max_calls,
            max_input_tokens=request.max_input_tokens,
            max_output_tokens=request.max_output_tokens,
            max_images=request.max_images,
            max_cost_microunits=request.max_cost_microunits,
            result=ModelValidationResult.NOT_RUN,
            safe_error_code="explicit_user_authorization_missing",
            evidence={
                "analytics_eligible": False,
                "external_network_accessed": False,
                "real_api_key_used": False,
                "cost_microunits": 0,
            },
            created_by=_require_member(self._context),
            started_at=now,
            completed_at=now,
            created_at=now,
        )
        self._session.add(run)
        self._session.flush()
        return run


def _current_policy(
    session: Session,
    *,
    workspace_id: UUID,
    capability: Capability,
    now: datetime,
    for_update: bool = False,
) -> ModelUsagePolicy | None:
    statement = (
        select(ModelUsagePolicy)
        .where(
            ModelUsagePolicy.workspace_id == workspace_id,
            ModelUsagePolicy.capability == capability.value,
            ModelUsagePolicy.effective_from <= now,
        )
        .order_by(
            ModelUsagePolicy.version.desc(),
            ModelUsagePolicy.id.desc(),
        )
        .limit(1)
    )
    return session.scalar(
        statement.with_for_update() if for_update else statement
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("usage governance clock must be timezone-aware")
    return value.astimezone(UTC)


def _require_member(context: WorkspaceContext) -> UUID:
    if context.member_id is None:
        raise ValueError("workspace member is required")
    return context.member_id
