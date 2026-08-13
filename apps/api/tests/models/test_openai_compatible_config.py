from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_session
from app.core.security import WorkspaceContext
from app.main import app
from app.modules.models.capabilities import AdapterStatus, Capability
from app.modules.models.config_service import ModelConfigService, SecretCipher
from app.modules.models.models import ModelConfig
from app.modules.models.models import NativeWebSearchStatus
from app.modules.workspace.models import Workspace
from app.modules.workspace.router import invite_attempts


def _service(role: str = "admin") -> tuple[Session, ModelConfigService, Workspace]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    workspace = Workspace(name="兼容模型合成工作区")
    session.add(workspace)
    session.flush()
    return (
        session,
        ModelConfigService(
            session,
            WorkspaceContext(
                workspace_id=workspace.id,
                member_id=None,
                role=role,
            ),
            cipher=SecretCipher("test-only-compatible-provider-key"),
        ),
        workspace,
    )


def _save(service: ModelConfigService) -> ModelConfig:
    return service.save(
        provider="openai_compatible",
        display_name="我的文本模型",
        model_id="example-chat",
        base_url="https://api.example.com/v1",
        capabilities=frozenset({Capability.TEXT}),
        status=AdapterStatus.COMMUNITY,
        api_key="synthetic-compatible-key-never-real",
    )


def test_openai_compatible_config_hides_key_and_full_endpoint() -> None:
    session, service, _ = _service()

    config = _save(service)
    public = service.public(config).model_dump(mode="json")

    assert config.display_name == "我的文本模型"
    assert config.endpoint_base_url == "https://api.example.com/v1"
    assert public["provider"] == "openai_compatible"
    assert public["display_name"] == "我的文本模型"
    assert public["endpoint_host"] == "api.example.com"
    serialized = service.public(config).model_dump_json()
    assert "synthetic-compatible-key-never-real" not in serialized
    assert "https://api.example.com/v1" not in serialized
    assert "encrypted_api_key" not in serialized
    assert public["native_web_search_status"] == NativeWebSearchStatus.UNSUPPORTED.value
    assert (
        public["native_web_search_safe_error_code"] == "NATIVE_WEB_SEARCH_NOT_ADAPTED"
    )
    session.close()


@pytest.mark.parametrize(
    ("capabilities", "status"),
    [
        (frozenset({Capability.TEXT, Capability.VISION}), AdapterStatus.COMMUNITY),
        (frozenset({Capability.TEXT}), AdapterStatus.EXPERIMENTAL),
        (frozenset({Capability.TEXT}), AdapterStatus.VERIFIED),
    ],
)
def test_openai_compatible_config_rejects_uncontrolled_contract(
    capabilities: frozenset[Capability],
    status: AdapterStatus,
) -> None:
    session, service, _ = _service()

    with pytest.raises(ValueError, match="OpenAI-compatible"):
        service.save(
            provider="openai_compatible",
            display_name="错误配置",
            model_id="example-chat",
            base_url="https://api.example.com/v1",
            capabilities=capabilities,
            status=status,
            api_key="synthetic-key",
        )
    session.close()


def test_non_admin_does_not_receive_compatible_endpoint_host() -> None:
    session, admin, workspace = _service()
    config = _save(admin)
    viewer = ModelConfigService(
        session,
        WorkspaceContext(
            workspace_id=workspace.id,
            member_id=None,
            role="viewer",
        ),
        cipher=SecretCipher("test-only-compatible-provider-key"),
    )

    public = viewer.public(config).model_dump(mode="json")

    assert public["endpoint_host"] is None
    session.close()


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


def _create_admin(client: TestClient) -> tuple[str, str]:
    workspace = client.post(
        "/v1/workspaces",
        json={"name": "兼容模型 API 工作区"},
    ).json()
    login = client.post(
        "/v1/sessions/invite",
        json={
            "code": workspace["admin_code"],
            "display_name": "模型管理员",
        },
    ).json()
    return workspace["workspace_id"], login["csrf_token"]


def test_admin_saves_openai_compatible_config_without_reading_secrets() -> None:
    with _client() as (client, engine):
        workspace_id, csrf = _create_admin(client)

        response = client.post(
            f"/v1/workspaces/{workspace_id}/model-configs",
            headers={"X-CSRF-Token": csrf},
            json={
                "provider": "openai_compatible",
                "display_name": "我的文本模型",
                "model_id": "example-chat",
                "base_url": "https://api.example.com/v1",
                "capabilities": ["text"],
                "status": "community",
                "api_key": "synthetic-compatible-key-never-real",
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["provider"] == "openai_compatible"
        assert body["display_name"] == "我的文本模型"
        assert body["endpoint_host"] == "api.example.com"
        assert "base_url" not in body
        assert "api_key" not in body
        assert "synthetic-compatible-key-never-real" not in response.text
        assert "https://api.example.com/v1" not in response.text
        with Session(engine) as session:
            stored = session.scalar(
                select(ModelConfig).where(
                    ModelConfig.workspace_id == UUID(workspace_id)
                )
            )
            assert stored is not None
            assert stored.endpoint_base_url == "https://api.example.com/v1"
            assert "synthetic-compatible" not in stored.encrypted_api_key
