from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_session
from app.core.security import WorkspaceContext
from app.main import app
from app.modules.models.capabilities import AdapterStatus, Capability
from app.modules.models.catalog import QIANWEN_TEXT_MODEL_ID, QianwenRegion
from app.modules.models.config_service import ModelConfigService, SecretCipher
from app.modules.models.models import ModelConfig
from app.modules.workspace.models import Workspace
from app.modules.workspace.permissions import PermissionDenied
from app.modules.workspace.router import invite_attempts


def _service(
    *,
    role: str = "admin",
) -> tuple[Session, ModelConfigService, Workspace]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    workspace = Workspace(name="千问配置合成测试工作区")
    session.add(workspace)
    session.flush()
    service = ModelConfigService(
        session,
        WorkspaceContext(
            workspace_id=workspace.id,
            member_id=None,
            role=role,
        ),
        cipher=SecretCipher("test-only-qianwen-encryption-key"),
    )
    return session, service, workspace


def test_qianwen_config_derives_catalog_capability_and_status() -> None:
    session, service, _ = _service()

    config = service.save(
        provider="qianwen",
        model_id=QIANWEN_TEXT_MODEL_ID,
        capabilities=frozenset({Capability.TEXT}),
        status=AdapterStatus.EXPERIMENTAL,
        api_key="sk-synthetic-qianwen-never-real",
        region=QianwenRegion.CN_BEIJING,
        provider_workspace_id="llm-abcd1234",
    )

    assert config.capabilities == ["text"]
    assert config.status.value == "experimental"
    assert config.region == "cn-beijing"
    assert config.provider_workspace_id == "llm-abcd1234"
    public = service.public(config).model_dump(mode="json")
    assert public["region"] == "cn-beijing"
    assert "provider_workspace_id" not in public
    assert "api_key" not in public
    assert "encrypted_api_key" not in public
    session.close()


@pytest.mark.parametrize(
    ("capabilities", "status"),
    [
        (
            frozenset({Capability.TEXT, Capability.VISION}),
            AdapterStatus.EXPERIMENTAL,
        ),
        (frozenset({Capability.TEXT}), AdapterStatus.VERIFIED),
    ],
)
def test_client_cannot_expand_qianwen_catalog_or_claim_verified(
    capabilities: frozenset[Capability],
    status: AdapterStatus,
) -> None:
    session, service, _ = _service()

    with pytest.raises(ValueError, match="Catalog"):
        service.save(
            provider="qianwen",
            model_id=QIANWEN_TEXT_MODEL_ID,
            capabilities=capabilities,
            status=status,
            api_key="sk-synthetic-qianwen-never-real",
            region=QianwenRegion.CN_BEIJING,
            provider_workspace_id="llm-abcd1234",
        )
    session.close()


def test_unknown_qianwen_model_and_missing_endpoint_fields_are_rejected() -> None:
    session, service, _ = _service()

    with pytest.raises(ValueError, match="Catalog"):
        service.save(
            provider="qianwen",
            model_id="qwen-latest",
            capabilities=frozenset({Capability.TEXT}),
            status=AdapterStatus.EXPERIMENTAL,
            api_key="sk-synthetic-qianwen-never-real",
            region=QianwenRegion.CN_BEIJING,
            provider_workspace_id="llm-abcd1234",
        )
    with pytest.raises(ValueError, match="region"):
        service.save(
            provider="qianwen",
            model_id=QIANWEN_TEXT_MODEL_ID,
            capabilities=frozenset({Capability.TEXT}),
            status=AdapterStatus.EXPERIMENTAL,
            api_key="sk-synthetic-qianwen-never-real",
            region=None,
            provider_workspace_id=None,
        )
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


def _create_and_login_admin(client: TestClient, name: str) -> tuple[str, str]:
    workspace = client.post("/v1/workspaces", json={"name": name}).json()
    login = client.post(
        "/v1/sessions/invite",
        json={
            "code": workspace["admin_code"],
            "display_name": f"{name}管理员",
        },
    ).json()
    return workspace["workspace_id"], login["csrf_token"]


def _qianwen_payload() -> dict[str, object]:
    return {
        "provider": "qianwen",
        "model_id": QIANWEN_TEXT_MODEL_ID,
        "region": "cn-beijing",
        "provider_workspace_id": "llm-abcd1234",
        "capabilities": ["text"],
        "status": "experimental",
        "api_key": "sk-synthetic-qianwen-never-real",
    }


def test_qianwen_api_hides_secrets_and_private_provider_workspace_id() -> None:
    with _client() as (client, engine):
        workspace_id, csrf = _create_and_login_admin(
            client,
            "千问 API 合成工作区",
        )

        created = client.post(
            f"/v1/workspaces/{workspace_id}/model-configs",
            headers={"X-CSRF-Token": csrf},
            json=_qianwen_payload(),
        )

        assert created.status_code == 201, created.text
        assert created.json()["region"] == "cn-beijing"
        for forbidden in (
            "api_key",
            "encrypted_api_key",
            "provider_workspace_id",
            "llm-abcd1234",
            "sk-synthetic-qianwen-never-real",
        ):
            assert forbidden not in created.text
        with Session(engine) as session:
            stored = session.scalar(
                select(ModelConfig).where(
                    ModelConfig.workspace_id == UUID(workspace_id)
                )
            )
            assert stored is not None
            assert stored.provider_workspace_id == "llm-abcd1234"
            assert "sk-synthetic" not in stored.encrypted_api_key


def test_viewer_cannot_create_config_and_cross_workspace_returns_404() -> None:
    with _client() as (client, _):
        workspace_a, admin_csrf = _create_and_login_admin(
            client,
            "权限工作区 A",
        )
        created = client.post(
            f"/v1/workspaces/{workspace_a}/model-configs",
            headers={"X-CSRF-Token": admin_csrf},
            json=_qianwen_payload(),
        )
        assert created.status_code == 201
        config_id = created.json()["id"]
        viewer_code = client.post(
            f"/v1/workspaces/{workspace_a}/members/codes",
            headers={"X-CSRF-Token": admin_csrf},
            json={"role": "viewer"},
        ).json()["code"]
        viewer = client.post(
            "/v1/sessions/invite",
            json={"code": viewer_code, "display_name": "只读成员"},
        ).json()
        denied = client.post(
            f"/v1/workspaces/{workspace_a}/model-configs",
            headers={"X-CSRF-Token": viewer["csrf_token"]},
            json=_qianwen_payload(),
        )
        assert denied.status_code == 403
        assert "sk-synthetic" not in denied.text

        workspace_b, csrf_b = _create_and_login_admin(
            client,
            "权限工作区 B",
        )
        hidden = client.patch(
            f"/v1/workspaces/{workspace_a}/model-configs/{config_id}",
            headers={"X-CSRF-Token": csrf_b},
            json={"status": "incompatible"},
        )
        assert workspace_b != workspace_a
        assert hidden.status_code == 404
        assert "llm-abcd1234" not in hidden.text


def test_unknown_qianwen_model_is_safe_422_and_cannot_claim_verified() -> None:
    with _client() as (client, _):
        workspace_id, csrf = _create_and_login_admin(
            client,
            "Catalog 拒绝工作区",
        )
        payload = _qianwen_payload()
        payload["model_id"] = "qwen-latest"
        payload["status"] = "verified"

        response = client.post(
            f"/v1/workspaces/{workspace_id}/model-configs",
            headers={"X-CSRF-Token": csrf},
            json=payload,
        )

        assert response.status_code == 422
        assert response.json()["detail"] == (
            "model is not present in the Provider Catalog"
        )


def test_viewer_cannot_write_and_cross_workspace_config_is_not_found() -> None:
    session, admin_service, workspace = _service()
    config = admin_service.save(
        provider="qianwen",
        model_id=QIANWEN_TEXT_MODEL_ID,
        capabilities=frozenset({Capability.TEXT}),
        status=AdapterStatus.EXPERIMENTAL,
        api_key="sk-synthetic-qianwen-never-real",
        region=QianwenRegion.AP_SOUTHEAST_1,
        provider_workspace_id="llm-abcd1234",
    )
    viewer = ModelConfigService(
        session,
        WorkspaceContext(
            workspace_id=workspace.id,
            member_id=uuid4(),
            role="viewer",
        ),
        cipher=SecretCipher("test-only-qianwen-encryption-key"),
    )
    with pytest.raises(PermissionDenied):
        viewer.save(
            provider="qianwen",
            model_id=QIANWEN_TEXT_MODEL_ID,
            capabilities=frozenset({Capability.TEXT}),
            status=AdapterStatus.EXPERIMENTAL,
            api_key="different-synthetic-key",
            region=QianwenRegion.CN_BEIJING,
            provider_workspace_id="llm-efgh5678",
        )

    other = Workspace(name="另一个合成工作区")
    session.add(other)
    session.flush()
    other_admin = ModelConfigService(
        session,
        WorkspaceContext(
            workspace_id=other.id,
            member_id=None,
            role="admin",
        ),
        cipher=SecretCipher("test-only-qianwen-encryption-key"),
    )
    with pytest.raises(LookupError, match="not found"):
        other_admin.set_status(config.id, AdapterStatus.INCOMPATIBLE)
    session.close()
