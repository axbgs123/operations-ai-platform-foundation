from datetime import UTC, datetime, timedelta
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.database import get_session
from app.core.security import WorkspaceContext
from app.main import app
from app.modules.models.capabilities import Capability
from app.modules.models.models import (
    ModelConfig,
    ModelConfigStatus,
    ModelContractValidationRun,
    ModelUsageAttempt,
    ModelUsageReservation,
)
from app.modules.models.usage import (
    HARD_POLICY_LIMITS,
    PRICING_VERSION,
    ControlledValidationRequest,
    ControlledValidationService,
    InMemoryUsageLeaseBackend,
    ModelUsageGovernor,
    ModelUsagePolicyInput,
    ModelUsagePolicyService,
    ProviderOperation,
    RedisUsageLeaseBackend,
    ReservationStatus,
    UsageAttemptOutcome,
    UsageEstimate,
    UsageGovernanceError,
    ValidationResult,
    estimate_cost_microunits,
)
from app.modules.workspace.models import Workspace
from app.modules.workspace.permissions import PermissionDenied
from app.modules.workspace.router import invite_attempts


NOW = datetime(2026, 7, 29, 23, 59, 59, tzinfo=UTC)


def _environment() -> tuple[
    sessionmaker[Session],
    Workspace,
    ModelConfig,
    UUID,
]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        workspace = Workspace(name="用量治理人工合成工作区")
        session.add(workspace)
        session.flush()
        config = ModelConfig(
            workspace_id=workspace.id,
            provider="qianwen",
            model_id="qwen3.5-plus-2026-04-20",
            capabilities=["text"],
            status=ModelConfigStatus.EXPERIMENTAL,
            encrypted_api_key="synthetic-ciphertext",
            region="cn-beijing",
            provider_workspace_id="llm-abcd1234",
            encryption_key_version="v1",
            credential_updated_at=NOW,
            configuration_revision=1,
        )
        session.add(config)
        session.commit()
        return factory, workspace, config, uuid4()


def _context(
    workspace_id: UUID,
    member_id: UUID,
    role: str = "admin",
) -> WorkspaceContext:
    return WorkspaceContext(
        workspace_id=workspace_id,
        member_id=member_id,
        role=role,  # type: ignore[arg-type]
    )


def _policy(**overrides: int | bool | str) -> ModelUsagePolicyInput:
    values: dict[str, int | bool | str] = {
        "capability": "text",
        "enabled": True,
        "max_concurrent_calls": 2,
        "max_calls_per_minute": 5,
        "daily_request_limit": 3,
        "daily_input_token_limit": 10_000,
        "daily_output_token_limit": 2_000,
        "daily_embedding_token_limit": 0,
        "daily_ocr_image_limit": 0,
        "daily_generated_image_limit": 0,
        "daily_cost_limit_microunits": 1_000_000,
        "currency": "CNY",
    }
    values.update(overrides)
    return ModelUsagePolicyInput.model_validate(values)


def _governor(
    factory: sessionmaker[Session],
    workspace: Workspace,
    config: ModelConfig,
    member_id: UUID,
    *,
    backend: InMemoryUsageLeaseBackend | None = None,
    clock=lambda: NOW,
    mock_mode: bool = False,
) -> ModelUsageGovernor:
    return ModelUsageGovernor(
        session_factory=factory,
        workspace_id=workspace.id,
        model_config_id=config.id,
        actor_id=member_id,
        task_id=uuid4(),
        provider="qianwen",
        model_id=config.model_id,
        region="cn-beijing",
        capability=Capability.TEXT,
        operation=ProviderOperation.TEXT_GENERATION,
        contract_version="qianwen-chat-json-v1",
        configuration_version="config-v1",
        lease_backend=backend or InMemoryUsageLeaseBackend(),
        clock=clock,
        mock_mode=mock_mode,
    )


def test_policy_requires_admin_and_enforces_server_hard_limits() -> None:
    factory, workspace, _, member_id = _environment()
    with factory() as session:
        editor = ModelUsagePolicyService(
            session,
            _context(workspace.id, member_id, "editor"),
            clock=lambda: NOW,
        )
        with pytest.raises(PermissionDenied):
            editor.save(_policy())

        admin = ModelUsagePolicyService(
            session,
            _context(workspace.id, member_id),
            clock=lambda: NOW,
        )
        saved = admin.save(_policy())
        session.commit()

        assert saved.version == 1
        assert saved.effective_from == NOW
        assert saved.currency == "CNY"
        assert HARD_POLICY_LIMITS.daily_cost_limit_microunits == 100_000_000
        with pytest.raises(ValueError, match="hard limit"):
            admin.save(
                _policy(
                    daily_cost_limit_microunits=(
                        HARD_POLICY_LIMITS.daily_cost_limit_microunits + 1
                    )
                )
            )


def test_zero_is_explicitly_disabled_not_unlimited() -> None:
    policy = _policy(daily_request_limit=0)
    assert policy.daily_request_limit == 0

    factory, workspace, config, member_id = _environment()
    with factory() as session:
        ModelUsagePolicyService(
            session,
            _context(workspace.id, member_id),
            clock=lambda: NOW,
        ).save(policy)
        session.commit()

    governor = _governor(factory, workspace, config, member_id)
    with pytest.raises(UsageGovernanceError) as captured:
        governor.begin_attempt(1, UsageEstimate(input_tokens=1))
    assert captured.value.code == "MODEL_USAGE_BUDGET_EXCEEDED"


def test_missing_policy_fails_closed_before_real_provider_call() -> None:
    factory, workspace, config, member_id = _environment()
    governor = _governor(factory, workspace, config, member_id)

    with pytest.raises(UsageGovernanceError) as captured:
        governor.begin_attempt(1, UsageEstimate(input_tokens=10))

    assert captured.value.code == "MODEL_USAGE_POLICY_REQUIRED"
    with factory() as session:
        assert session.scalars(select(ModelUsageReservation)).all() == []
        assert session.scalars(select(ModelUsageAttempt)).all() == []


def test_mock_attempt_is_not_analytics_eligible_and_consumes_no_budget() -> None:
    factory, workspace, config, member_id = _environment()
    governor = _governor(
        factory,
        workspace,
        config,
        member_id,
        mock_mode=True,
    )

    handle = governor.begin_attempt(
        1,
        UsageEstimate(input_tokens=999, generated_images=1),
    )
    governor.finish_attempt(
        handle,
        outcome=UsageAttemptOutcome.SUCCEEDED,
        actual=UsageEstimate(input_tokens=999, generated_images=1),
        latency_ms=12,
    )

    assert handle.analytics_eligible is False
    with factory() as session:
        assert session.scalars(select(ModelUsageReservation)).all() == []
        assert session.scalars(select(ModelUsageAttempt)).all() == []


@pytest.mark.parametrize(
    ("region", "estimate", "expected"),
    [
        (
            "cn-beijing",
            UsageEstimate(input_tokens=1_000_000, output_tokens=1_000_000),
            5_600_000,
        ),
        (
            "ap-southeast-1",
            UsageEstimate(input_tokens=1_000_000, output_tokens=1_000_000),
            20_550_000,
        ),
    ],
)
def test_pricing_uses_integer_microunits_without_float_drift(
    region: str,
    estimate: UsageEstimate,
    expected: int,
) -> None:
    assert (
        estimate_cost_microunits(
            model_id="qwen3.5-plus-2026-04-20",
            region=region,
            estimate=estimate,
        )
        == expected
    )
    assert PRICING_VERSION == "aliyun-public-2026-07-29-v1"


def test_reservation_settlement_and_unknown_are_auditable_per_attempt() -> None:
    factory, workspace, config, member_id = _environment()
    with factory() as session:
        ModelUsagePolicyService(
            session,
            _context(workspace.id, member_id),
            clock=lambda: NOW,
        ).save(_policy())
        session.commit()
    governor = _governor(factory, workspace, config, member_id)

    succeeded = governor.begin_attempt(
        1,
        UsageEstimate(input_tokens=100, output_tokens=20),
    )
    governor.finish_attempt(
        succeeded,
        outcome=UsageAttemptOutcome.SUCCEEDED,
        actual=UsageEstimate(input_tokens=80, output_tokens=10),
        latency_ms=45,
        provider_request_id="request-safe-1",
    )
    unknown = governor.begin_attempt(
        2,
        UsageEstimate(input_tokens=100, output_tokens=20),
    )
    governor.finish_attempt(
        unknown,
        outcome=UsageAttemptOutcome.PROVIDER_OUTCOME_UNKNOWN,
        actual=None,
        latency_ms=30,
        stable_error_code="MODEL_PROVIDER_OUTCOME_UNKNOWN",
    )

    with factory() as session:
        reservations = session.scalars(
            select(ModelUsageReservation).order_by(
                ModelUsageReservation.provider_attempt_number
            )
        ).all()
        attempts = session.scalars(
            select(ModelUsageAttempt).order_by(
                ModelUsageAttempt.provider_attempt_number
            )
        ).all()

    assert [item.status for item in reservations] == [
        ReservationStatus.SETTLED,
        ReservationStatus.UNKNOWN,
    ]
    assert reservations[1].reserved_cost_microunits > 0
    assert [item.status for item in attempts] == [
        UsageAttemptOutcome.SUCCEEDED,
        UsageAttemptOutcome.PROVIDER_OUTCOME_UNKNOWN,
    ]
    assert attempts[0].provider_request_id == "request-safe-1"
    assert attempts[0].pricing_version == PRICING_VERSION
    assert attempts[0].settled_cost_microunits is not None
    assert attempts[1].settled_cost_microunits is None
    assert attempts[0].usage_basis == "settled"
    assert attempts[1].usage_basis == "unknown"
    forbidden = (
        "prompt",
        "output",
        "document",
        "image_url",
        "api_key",
        "provider_workspace_id",
        "authorization",
        "cookie",
    )
    columns = {column.name for column in ModelUsageAttempt.__table__.columns}
    assert columns.isdisjoint(forbidden)


def test_known_unbilled_failure_releases_budget_but_cancel_does_not() -> None:
    factory, workspace, config, member_id = _environment()
    with factory() as session:
        ModelUsagePolicyService(
            session,
            _context(workspace.id, member_id),
            clock=lambda: NOW,
        ).save(_policy())
        session.commit()
    governor = _governor(factory, workspace, config, member_id)

    failed = governor.begin_attempt(
        1, UsageEstimate(input_tokens=100, output_tokens=20)
    )
    governor.finish_attempt(
        failed,
        outcome=UsageAttemptOutcome.FAILED_UNBILLED,
        actual=None,
        latency_ms=1,
        stable_error_code="MODEL_AUTHENTICATION_FAILED",
    )
    cancelled = governor.begin_attempt(
        2, UsageEstimate(input_tokens=100, output_tokens=20)
    )
    governor.finish_attempt(
        cancelled,
        outcome=UsageAttemptOutcome.CANCELLED_UNKNOWN,
        actual=None,
        latency_ms=1,
    )

    with factory() as session:
        rows = session.scalars(
            select(ModelUsageReservation).order_by(
                ModelUsageReservation.provider_attempt_number
            )
        ).all()
    assert [row.status for row in rows] == [
        ReservationStatus.RELEASED,
        ReservationStatus.UNKNOWN,
    ]


def test_daily_budget_uses_utc_boundary() -> None:
    factory, workspace, config, member_id = _environment()
    current = [NOW]
    def clock() -> datetime:
        return current[0]
    with factory() as session:
        ModelUsagePolicyService(
            session,
            _context(workspace.id, member_id),
            clock=clock,
        ).save(_policy(daily_request_limit=1))
        session.commit()
    governor = _governor(
        factory,
        workspace,
        config,
        member_id,
        clock=clock,
    )
    handle = governor.begin_attempt(1, UsageEstimate(input_tokens=1))
    governor.finish_attempt(
        handle,
        outcome=UsageAttemptOutcome.SUCCEEDED,
        actual=UsageEstimate(input_tokens=1),
        latency_ms=1,
    )
    with pytest.raises(UsageGovernanceError):
        governor.begin_attempt(2, UsageEstimate(input_tokens=1))

    current[0] = NOW + timedelta(seconds=2)
    next_day = governor.begin_attempt(3, UsageEstimate(input_tokens=1))
    assert next_day.reservation_id is not None


def test_concurrency_lease_uses_token_fencing_and_safe_expiry() -> None:
    current = [0.0]
    backend = InMemoryUsageLeaseBackend(clock=lambda: current[0])
    key = "workspace:text"

    first = backend.acquire(key, limit=1, ttl_seconds=30)
    assert first is not None
    assert backend.acquire(key, limit=1, ttl_seconds=30) is None
    assert backend.renew(key, "wrong-token", ttl_seconds=30) is False
    assert backend.release(key, "wrong-token") is False
    assert backend.renew(key, first, ttl_seconds=30) is True

    current[0] = 31.0
    second = backend.acquire(key, limit=1, ttl_seconds=30)
    assert second is not None
    assert second != first
    assert backend.release(key, first) is False
    assert backend.release(key, second) is True


class _FakeRedis:
    def __init__(self, replies: list[object]) -> None:
        self.replies = replies
        self.calls: list[tuple[str, int, tuple[object, ...]]] = []

    def eval(
        self,
        script: str,
        key_count: int,
        *values: object,
    ) -> object:
        self.calls.append((script, key_count, values))
        return self.replies.pop(0)


def test_redis_usage_backend_uses_atomic_fenced_lua_operations() -> None:
    redis = _FakeRedis(["lease-token", 1, 1, 0])
    backend = RedisUsageLeaseBackend(redis)  # type: ignore[arg-type]

    assert backend.acquire("lease-key", limit=2, ttl_seconds=60) == (
        "lease-token"
    )
    assert backend.renew("lease-key", "lease-token", ttl_seconds=60) is True
    assert backend.release("lease-key", "lease-token") is True
    assert (
        backend.check_rate("rate-key", limit=3, window_seconds=60) is False
    )

    assert len(redis.calls) == 4
    assert all(key_count == 1 for _, key_count, _ in redis.calls)
    assert redis.calls[0][2][0] == "lease-key"
    assert redis.calls[1][2] == ("lease-key", "lease-token", 60)
    assert redis.calls[2][2] == ("lease-key", "lease-token")
    assert redis.calls[3][2] == ("rate-key", 3, 60)


def test_worker_heartbeat_renews_active_provider_lease() -> None:
    factory, workspace, config, member_id = _environment()
    backend = InMemoryUsageLeaseBackend()
    with factory() as session:
        ModelUsagePolicyService(
            session,
            _context(workspace.id, member_id),
            clock=lambda: NOW,
        ).save(_policy())
        session.commit()
    governor = _governor(
        factory,
        workspace,
        config,
        member_id,
        backend=backend,
    )
    handle = governor.begin_attempt(1, UsageEstimate(input_tokens=1))

    with governor.heartbeat(handle, interval_seconds=0.001):
        import time

        time.sleep(0.01)

    assert governor.renew(handle) is True


def test_validation_is_not_run_without_explicit_external_authorization() -> None:
    factory, workspace, config, member_id = _environment()
    with factory() as session:
        service = ControlledValidationService(
            session,
            _context(workspace.id, member_id),
            real_calls_authorized=False,
            clock=lambda: NOW,
        )
        run = service.create(
            ControlledValidationRequest(
                model_config_id=config.id,
                region="cn-beijing",
                capability=Capability.TEXT,
                model_id=config.model_id,
                max_calls=1,
                max_input_tokens=100,
                max_output_tokens=100,
                max_images=0,
                max_cost_microunits=1000,
                confirm_real_call=True,
            )
        )
        session.commit()

        assert run.result is ValidationResult.NOT_RUN
        assert run.safe_error_code == "explicit_user_authorization_missing"
        assert run.completed_at == NOW
        assert session.scalar(
            select(ModelContractValidationRun).where(
                ModelContractValidationRun.id == run.id
            )
        ) is not None


def test_non_admin_cannot_create_validation() -> None:
    factory, workspace, config, member_id = _environment()
    with factory() as session:
        service = ControlledValidationService(
            session,
            _context(workspace.id, member_id, "editor"),
            real_calls_authorized=False,
            clock=lambda: NOW,
        )
        with pytest.raises(PermissionDenied):
            service.create(
                ControlledValidationRequest(
                    model_config_id=config.id,
                    region="cn-beijing",
                    capability=Capability.TEXT,
                    model_id=config.model_id,
                    max_calls=1,
                    max_input_tokens=100,
                    max_output_tokens=100,
                    max_images=0,
                    max_cost_microunits=1000,
                    confirm_real_call=True,
                )
            )


@contextmanager
def _client() -> Iterator[tuple[TestClient, object]]:
    invite_attempts.clear()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def override_session() -> Iterator[Session]:
        with Session(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            yield client, engine
    finally:
        app.dependency_overrides.clear()


def _login_admin(client: TestClient, name: str) -> tuple[str, str]:
    workspace = client.post("/v1/workspaces", json={"name": name}).json()
    login = client.post(
        "/v1/sessions/invite",
        json={
            "code": workspace["admin_code"],
            "display_name": f"{name}管理员",
        },
    ).json()
    return workspace["workspace_id"], login["csrf_token"]


def _api_policy() -> dict[str, object]:
    return _policy().model_dump(mode="json")


def _api_config() -> dict[str, object]:
    return {
        "provider": "qianwen",
        "model_id": "qwen3.5-plus-2026-04-20",
        "region": "cn-beijing",
        "provider_workspace_id": "llm-abcd1234",
        "capabilities": ["text"],
        "status": "experimental",
        "api_key": "synthetic-key-never-real",
    }


def test_admin_usage_api_returns_safe_policy_summary_and_not_run_validation() -> None:
    with _client() as (client, _):
        workspace_id, csrf = _login_admin(client, "用量 API 工作区")
        created_config = client.post(
            f"/v1/workspaces/{workspace_id}/model-configs",
            headers={"X-CSRF-Token": csrf},
            json=_api_config(),
        )
        assert created_config.status_code == 201, created_config.text

        policy = client.put(
            f"/v1/workspaces/{workspace_id}/model-usage/policy",
            headers={"X-CSRF-Token": csrf},
            json=_api_policy(),
        )
        assert policy.status_code == 200, policy.text
        assert policy.json()["version"] == 1
        assert policy.json()["utc_day_boundary"] == "00:00:00Z"

        summary = client.get(
            f"/v1/workspaces/{workspace_id}/model-usage/summary"
        )
        assert summary.status_code == 200, summary.text
        assert summary.json() == {
            "workspace_id": workspace_id,
            "utc_day": datetime.now(UTC).date().isoformat(),
            "mock_attempts": 0,
            "real_attempts": 0,
            "estimated_cost_microunits": 0,
            "settled_cost_microunits": 0,
            "unknown_reserved_cost_microunits": 0,
            "currency": "CNY",
            "sample_status": "insufficient_sample",
        }

        validation = client.post(
            f"/v1/workspaces/{workspace_id}/model-validations",
            headers={"X-CSRF-Token": csrf},
            json={
                "model_config_id": created_config.json()["id"],
                "region": "cn-beijing",
                "capability": "text",
                "model_id": "qwen3.5-plus-2026-04-20",
                "max_calls": 1,
                "max_input_tokens": 100,
                "max_output_tokens": 100,
                "max_images": 0,
                "max_cost_microunits": 1000,
                "confirm_real_call": True,
            },
        )
        assert validation.status_code == 201, validation.text
        assert validation.json()["result"] == "not_run"
        assert (
            validation.json()["safe_error_code"]
            == "explicit_user_authorization_missing"
        )
        assert validation.json()["experimental"] is True
        for forbidden in (
            "synthetic-key-never-real",
            "llm-abcd1234",
            "provider_workspace_id",
            "encrypted_api_key",
            '"prompt":',
            '"output":',
        ):
            assert forbidden not in (
                policy.text + summary.text + validation.text
            )


def test_editor_cannot_manage_policy_or_validation_and_viewer_is_status_only() -> None:
    with _client() as (client, _):
        workspace_id, csrf = _login_admin(client, "用量权限工作区")
        editor_code = client.post(
            f"/v1/workspaces/{workspace_id}/members/codes",
            headers={"X-CSRF-Token": csrf},
            json={"role": "editor"},
        ).json()["code"]
        viewer_code = client.post(
            f"/v1/workspaces/{workspace_id}/members/codes",
            headers={"X-CSRF-Token": csrf},
            json={"role": "viewer"},
        ).json()["code"]
        editor = client.post(
            "/v1/sessions/invite",
            json={"code": editor_code, "display_name": "编辑者"},
        ).json()
        denied_policy = client.put(
            f"/v1/workspaces/{workspace_id}/model-usage/policy",
            headers={"X-CSRF-Token": editor["csrf_token"]},
            json=_api_policy(),
        )
        denied_validation = client.post(
            f"/v1/workspaces/{workspace_id}/model-validations",
            headers={"X-CSRF-Token": editor["csrf_token"]},
            json={
                "model_config_id": str(uuid4()),
                "region": "cn-beijing",
                "capability": "text",
                "model_id": "qwen3.5-plus-2026-04-20",
                "max_calls": 1,
                "max_input_tokens": 100,
                "max_output_tokens": 100,
                "max_images": 0,
                "max_cost_microunits": 1000,
                "confirm_real_call": True,
            },
        )
        assert denied_policy.status_code == 403
        assert denied_validation.status_code == 403

        viewer = client.post(
            "/v1/sessions/invite",
            json={
                "code": viewer_code,
                "display_name": "查看者",
            },
        ).json()
        assert viewer["csrf_token"]
        safe_status = client.get(
            f"/v1/workspaces/{workspace_id}/model-configs"
        )
        detailed = client.get(
            f"/v1/workspaces/{workspace_id}/model-usage/summary"
        )
        assert safe_status.status_code == 200
        assert detailed.status_code == 403


def test_usage_api_cross_workspace_is_hidden_as_not_found() -> None:
    with _client() as (client, _):
        workspace_a, _ = _login_admin(client, "用量隔离 A")
        workspace_b, csrf_b = _login_admin(client, "用量隔离 B")

        response = client.put(
            f"/v1/workspaces/{workspace_a}/model-usage/policy",
            headers={"X-CSRF-Token": csrf_b},
            json=_api_policy(),
        )

        assert workspace_a != workspace_b
        assert response.status_code == 404
        assert "workspace" in response.text
