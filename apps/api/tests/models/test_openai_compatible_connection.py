import httpx
from pydantic import SecretStr
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.security import WorkspaceContext
from app.modules.models.capabilities import AdapterStatus, Capability
from app.modules.models.config_service import ModelConfigService, SecretCipher
from app.modules.models.openai_compatible_connection import (
    probe_openai_compatible_connection,
)
from app.modules.models.usage import (
    ControlledValidationRequest,
    ControlledValidationService,
)
from app.modules.workspace.models import MemberRole, Workspace, WorkspaceMember


def _probe(response: httpx.Response, model_id: str = "expected-model") -> str | None:
    return probe_openai_compatible_connection(
        api_key=SecretStr("synthetic-key-never-real"),
        base_url="https://api.example.com/v1",
        model_id=model_id,
        app_env="production",
        transport=httpx.MockTransport(lambda request: response),
        resolver=lambda host, port, type: [
            (2, 1, 6, "", ("93.184.216.34", port))
        ],
    )


def test_connection_probe_accepts_configured_model_without_generation() -> None:
    response = httpx.Response(
        200,
        json={
            "object": "list",
            "data": [{"id": "expected-model", "object": "model"}],
        },
    )

    assert _probe(response) is None


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(401), "MODEL_AUTHENTICATION_FAILED"),
        (httpx.Response(403), "MODEL_AUTHENTICATION_FAILED"),
        (httpx.Response(429), "MODEL_RATE_LIMITED"),
        (httpx.Response(500), "MODEL_PROVIDER_UNAVAILABLE"),
        (httpx.Response(302, headers={"location": "https://other.test"}), "MODEL_PROVIDER_UNAVAILABLE"),
        (httpx.Response(200, json={"object": "list", "data": []}), "MODEL_NOT_FOUND"),
        (httpx.Response(200, json={"data": "invalid"}), "MODEL_INVALID_RESPONSE"),
    ],
)
def test_connection_probe_returns_only_stable_errors(
    response: httpx.Response,
    expected: str,
) -> None:
    assert _probe(response) == expected


def test_connection_probe_rejects_unsafe_target_before_http() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"data": []}, request=request)

    result = probe_openai_compatible_connection(
        api_key=SecretStr("synthetic-key-never-real"),
        base_url="http://169.254.169.254/v1",
        model_id="expected-model",
        app_env="production",
        transport=httpx.MockTransport(handler),
    )

    assert result == "MODEL_ENDPOINT_UNSAFE"
    assert called is False


def test_controlled_validation_accepts_provider_managed_region() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        workspace = Workspace(name="兼容连接验收工作区")
        session.add(workspace)
        session.flush()
        member = WorkspaceMember(
            workspace_id=workspace.id,
            display_name="管理员",
            role=MemberRole.ADMIN,
        )
        session.add(member)
        session.flush()
        context = WorkspaceContext(
            workspace_id=workspace.id,
            member_id=member.id,
            role="admin",
        )
        config = ModelConfigService(
            session,
            context,
            cipher=SecretCipher("test-only-compatible-validation-key"),
        ).save(
            provider="openai_compatible",
            display_name="我的文本模型",
            model_id="expected-model",
            base_url="https://api.example.com/v1",
            capabilities=frozenset({Capability.TEXT}),
            status=AdapterStatus.COMMUNITY,
            api_key="synthetic-key-never-real",
        )

        run = ControlledValidationService(
            session,
            context,
            real_calls_authorized=True,
            connection_probe=lambda target: None,
        ).create(
            ControlledValidationRequest(
                model_config_id=config.id,
                region="provider-managed",
                capability=Capability.TEXT,
                model_id="expected-model",
                max_calls=1,
                max_input_tokens=0,
                max_output_tokens=0,
                max_images=0,
                max_cost_microunits=1,
                confirm_real_call=True,
            )
        )

        assert run.result.value == "passed"
        assert run.region == "provider-managed"
        assert run.contract_version == "openai-compatible-chat-json-v1"
