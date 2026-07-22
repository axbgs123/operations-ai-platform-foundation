import logging
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_session
from app.core.config import DEFAULT_MODEL_SECRET_ENCRYPTION_KEY, Settings
from app.core.security import WorkspaceContext
from app.main import app
from app.modules.models.capabilities import AdapterStatus, Capability
from app.modules.models.config_service import (
    ModelConfigService,
    ModelConfigurationRequired,
    SecretCipher,
)
from app.modules.models.models import ModelConfig
from app.modules.workspace.models import Workspace
from app.modules.workspace.permissions import PermissionDenied
from app.modules.workspace.router import invite_attempts


def configured_service() -> tuple[Session, ModelConfigService, Workspace]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    workspace = Workspace(name="模型配置测试工作区")
    session.add(workspace)
    session.flush()
    service = ModelConfigService(
        session,
        WorkspaceContext(
            workspace_id=workspace.id,
            member_id=None,
            role="admin",
        ),
        cipher=SecretCipher("test-only-model-secret-encryption-key"),
    )
    return session, service, workspace


@contextmanager
def configured_client() -> Iterator[TestClient]:
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
            yield client
    finally:
        app.dependency_overrides.clear()


def create_admin(client: TestClient) -> tuple[str, str]:
    workspace = client.post(
        "/v1/workspaces",
        json={"name": "模型 API 测试工作区"},
    ).json()
    login = client.post(
        "/v1/sessions/invite",
        json={
            "code": workspace["admin_code"],
            "display_name": "模型管理员",
        },
    ).json()
    return workspace["workspace_id"], login["csrf_token"]


def test_api_key_is_encrypted_at_rest_and_absent_from_public_response_and_logs(
    caplog,
) -> None:
    session, service, workspace = configured_service()
    secret = "sk-synthetic-never-real"
    caplog.set_level(logging.DEBUG)

    config = service.save(
        provider="contract-provider",
        model_id="contract-text-v1",
        capabilities=frozenset({Capability.TEXT}),
        status=AdapterStatus.EXPERIMENTAL,
        api_key=secret,
    )
    session.flush()
    persisted = session.scalar(
        select(ModelConfig).where(ModelConfig.workspace_id == workspace.id)
    )
    assert persisted is not None
    public = service.public(config).model_dump(mode="json")

    assert secret not in persisted.encrypted_api_key
    assert service.decrypt_key(config.id).get_secret_value() == secret
    assert "api_key" not in public
    assert "encrypted_api_key" not in public
    assert secret not in caplog.text
    assert secret not in repr(service.decrypt_key(config.id))
    assert persisted.encryption_key_version == "v1"
    session.close()


def test_status_changes_are_persisted_but_incompatible_configs_cannot_be_selected() -> None:
    session, service, _ = configured_service()
    config = service.save(
        provider="contract-provider",
        model_id="contract-multimodal-v1",
        capabilities=frozenset({Capability.TEXT, Capability.VISION}),
        status=AdapterStatus.COMMUNITY,
        api_key="synthetic-key",
    )

    service.set_status(config.id, AdapterStatus.INCOMPATIBLE)

    try:
        service.resolve({Capability.TEXT})
    except ModelConfigurationRequired as error:
        assert error.code == "MODEL_CONFIGURATION_REQUIRED"
        assert "配置" in str(error)
    else:
        raise AssertionError("incompatible model config must not be selected")
    session.close()


def test_no_configuration_returns_actionable_degradation_without_breaking_data() -> None:
    session, service, _ = configured_service()

    try:
        service.resolve({Capability.EMBEDDING})
    except ModelConfigurationRequired as error:
        assert error.required_capabilities == (Capability.EMBEDDING,)
        assert error.action == "configure_model"
        assert "管理员" in str(error)
    else:
        raise AssertionError("missing config must return a degradation result")
    session.close()


def test_persisted_selection_prefers_higher_adapter_status() -> None:
    session, service, _ = configured_service()
    service.save(
        provider="community-provider",
        model_id="community-text",
        capabilities=frozenset({Capability.TEXT}),
        status=AdapterStatus.COMMUNITY,
        api_key="community-synthetic-key",
    )
    expected = service.save(
        provider="experimental-provider",
        model_id="experimental-text",
        capabilities=frozenset({Capability.TEXT}),
        status=AdapterStatus.EXPERIMENTAL,
        api_key="experimental-synthetic-key",
    )

    selected = service.resolve({Capability.TEXT})

    assert selected.id == expected.id
    session.close()


def test_model_configuration_is_workspace_scoped() -> None:
    session, service, _ = configured_service()
    config = service.save(
        provider="contract-provider",
        model_id="workspace-one",
        capabilities=frozenset({Capability.TEXT}),
        status=AdapterStatus.EXPERIMENTAL,
        api_key="workspace-one-key",
    )
    other = Workspace(name="另一个工作区")
    session.add(other)
    session.flush()
    other_service = ModelConfigService(
        session,
        WorkspaceContext(workspace_id=other.id, member_id=None, role="admin"),
        cipher=SecretCipher("test-only-model-secret-encryption-key"),
    )

    assert other_service.list_public() == []
    try:
        other_service.decrypt_key(config.id)
    except LookupError as error:
        assert "not found" in str(error)
    else:
        raise AssertionError("cross-workspace key decryption must be rejected")
    session.close()


def test_only_admin_can_manage_model_credentials() -> None:
    session, _, workspace = configured_service()
    editor_service = ModelConfigService(
        session,
        WorkspaceContext(workspace_id=workspace.id, member_id=None, role="editor"),
        cipher=SecretCipher("test-only-model-secret-encryption-key"),
    )

    try:
        editor_service.save(
            provider="contract-provider",
            model_id="forbidden-editor-model",
            capabilities=frozenset({Capability.TEXT}),
            status=AdapterStatus.EXPERIMENTAL,
            api_key="synthetic-key",
        )
    except PermissionDenied as error:
        assert "manage_models" in str(error)
    else:
        raise AssertionError("editors must not manage model credentials")
    session.close()


def test_uncontracted_adapter_cannot_claim_verified_status() -> None:
    session, service, _ = configured_service()

    try:
        service.save(
            provider="uncontracted-provider",
            model_id="uncontracted-model",
            capabilities=frozenset({Capability.TEXT}),
            status=AdapterStatus.VERIFIED,
            api_key="synthetic-key",
        )
    except ValueError as error:
        assert "contract" in str(error)
    else:
        raise AssertionError("verified status requires a passing adapter contract")
    session.close()


def test_saving_the_same_model_rotates_the_encrypted_key() -> None:
    session, service, _ = configured_service()
    original = service.save(
        provider="rotation-provider",
        model_id="rotation-model",
        capabilities=frozenset({Capability.TEXT}),
        status=AdapterStatus.EXPERIMENTAL,
        api_key="old-synthetic-key",
    )
    original_ciphertext = original.encrypted_api_key

    rotated = service.save(
        provider="rotation-provider",
        model_id="rotation-model",
        capabilities=frozenset({Capability.TEXT, Capability.VISION}),
        status=AdapterStatus.COMMUNITY,
        api_key="new-synthetic-key",
    )

    assert rotated.id == original.id
    assert rotated.encrypted_api_key != original_ciphertext
    assert service.decrypt_key(rotated.id).get_secret_value() == "new-synthetic-key"
    assert service.public(rotated).status is AdapterStatus.COMMUNITY
    session.close()


def test_stale_model_lookup_recovers_from_concurrent_unique_conflict(
    monkeypatch,
) -> None:
    session, service, workspace = configured_service()
    existing = service.save(
        provider="concurrent-provider",
        model_id="concurrent-model",
        capabilities=frozenset({Capability.TEXT}),
        status=AdapterStatus.EXPERIMENTAL,
        api_key="old-synthetic-key",
    )
    session.commit()
    existing_id = existing.id
    real_scalar = session.scalar
    calls = 0

    def stale_once(statement):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return real_scalar(statement)

    monkeypatch.setattr(session, "scalar", stale_once)
    rotated = service.save(
        provider="concurrent-provider",
        model_id="concurrent-model",
        capabilities=frozenset({Capability.TEXT, Capability.VISION}),
        status=AdapterStatus.COMMUNITY,
        api_key="new-synthetic-key",
    )

    assert rotated.id == existing_id
    assert rotated.workspace_id == workspace.id
    assert service.decrypt_key(rotated.id).get_secret_value() == "new-synthetic-key"
    session.close()


def test_model_config_list_has_deterministic_provider_and_model_order() -> None:
    session, service, _ = configured_service()
    for provider, model_id in (("z-provider", "z-model"), ("a-provider", "a-model")):
        service.save(
            provider=provider,
            model_id=model_id,
            capabilities=frozenset({Capability.TEXT}),
            status=AdapterStatus.EXPERIMENTAL,
            api_key=f"{provider}-synthetic-key",
        )

    assert [item.provider for item in service.list_public()] == [
        "a-provider",
        "z-provider",
    ]
    session.close()


def test_non_development_settings_reject_default_model_encryption_key() -> None:
    for app_env in ("production", "staging", "preview", "qa", "test", "prod"):
        try:
            Settings(
                app_env=app_env,
                model_secret_encryption_key=SecretStr(
                    DEFAULT_MODEL_SECRET_ENCRYPTION_KEY
                ),
            )
        except ValidationError as error:
            assert "model secret encryption key" in str(error).lower()
        else:
            raise AssertionError(f"{app_env} must reject the development key")

    configured = Settings(
        app_env="production",
        model_secret_encryption_key=SecretStr("production-test-only-high-entropy-key"),
    )
    assert configured.model_secret_encryption_key.get_secret_value().startswith(
        "production-test-only"
    )


def test_non_development_settings_reject_weak_model_encryption_key() -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(
            app_env="production",
            model_secret_encryption_key=SecretStr("weak-key"),
        )


def test_model_config_api_never_returns_secret_and_supports_status_changes() -> None:
    with configured_client() as client:
        workspace_id, csrf = create_admin(client)
        secret = "sk-api-synthetic-never-real"
        created = client.post(
            f"/v1/workspaces/{workspace_id}/model-configs",
            headers={"X-CSRF-Token": csrf},
            json={
                "provider": "contract-provider",
                "model_id": "contract-all-v1",
                "capabilities": ["text", "vision", "image", "embedding"],
                "status": "experimental",
                "api_key": secret,
            },
        )

        assert created.status_code == 201
        assert secret not in created.text
        assert "api_key" not in created.json()
        config_id = created.json()["id"]

        listed = client.get(f"/v1/workspaces/{workspace_id}/model-configs")
        assert listed.status_code == 200
        assert listed.json() == [created.json()]
        assert secret not in listed.text

        changed = client.patch(
            f"/v1/workspaces/{workspace_id}/model-configs/{config_id}",
            headers={"X-CSRF-Token": csrf},
            json={"status": "incompatible"},
        )
        assert changed.status_code == 200
        assert changed.json()["status"] == "incompatible"


def test_model_selection_api_returns_actionable_degradation_without_config() -> None:
    with configured_client() as client:
        workspace_id, _ = create_admin(client)

        response = client.get(
            f"/v1/workspaces/{workspace_id}/model-configs/selection",
            params={"capability": "image"},
        )

        assert response.status_code == 409
        assert response.json()["detail"] == {
            "code": "MODEL_CONFIGURATION_REQUIRED",
            "message": "请联系管理员配置支持 image 的模型",
            "action": "configure_model",
            "required_capabilities": ["image"],
        }
