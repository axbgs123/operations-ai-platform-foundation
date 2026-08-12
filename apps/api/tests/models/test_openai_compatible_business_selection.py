from uuid import uuid4

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.security import WorkspaceContext
from app.modules.models.adapter_factory import (
    ModelBinding,
    create_workspace_model_adapter,
)
from app.modules.models.adapters.openai_compatible import (
    OpenAICompatibleTextProvider,
)
from app.modules.models.capabilities import AdapterStatus, Capability
from app.modules.models.config_service import (
    ModelConfigService,
    SecretCipher,
    model_configuration_version,
)
from app.modules.workspace.models import Workspace


def test_factory_builds_workspace_scoped_openai_compatible_adapter() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        workspace = Workspace(name="兼容 Provider 工厂测试")
        session.add(workspace)
        session.flush()
        cipher = SecretCipher("test-only-compatible-factory-key")
        config = ModelConfigService(
            session,
            WorkspaceContext(
                workspace_id=workspace.id,
                member_id=None,
                role="admin",
            ),
            cipher=cipher,
        ).save(
            provider="openai_compatible",
            display_name="我的模型",
            model_id="example-chat",
            base_url="https://api.example.com/v1",
            capabilities=frozenset({Capability.TEXT}),
            status=AdapterStatus.COMMUNITY,
            api_key="synthetic-key-never-real",
        )
        expected = ModelBinding(
            provider="openai_compatible",
            model_id="example-chat",
            contract_version="openai-compatible-chat-json-v1",
            configuration_version=model_configuration_version(config),
        )

        bound = create_workspace_model_adapter(
            session=session,
            workspace_id=workspace.id,
            model_config_id=config.id,
            required_capability=Capability.TEXT,
            cipher=cipher,
            mock_mode=False,
            expected=expected,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"choices": []})
            ),
            app_env="production",
            compatible_resolver=lambda host, port, type: [
                (2, 1, 6, "", ("93.184.216.34", port))
            ],
        )

        assert isinstance(bound.adapter, OpenAICompatibleTextProvider)
        assert bound.binding == expected

        other_workspace_id = uuid4()
        try:
            create_workspace_model_adapter(
                session=session,
                workspace_id=other_workspace_id,
                model_config_id=config.id,
                required_capability=Capability.TEXT,
                cipher=cipher,
                mock_mode=False,
                expected=expected,
            )
        except RuntimeError as error:
            assert getattr(error, "code", None) == "MODEL_CONFIGURATION_REQUIRED"
        else:
            raise AssertionError("cross-workspace model selection must fail")


def test_analysis_binding_can_select_workspace_compatible_text_model() -> None:
    from app.modules.analysis.service import resolve_analysis_model_binding

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        workspace = Workspace(name="兼容 Provider 分析测试")
        session.add(workspace)
        session.flush()
        cipher = SecretCipher("test-only-compatible-analysis-key")
        config = ModelConfigService(
            session,
            WorkspaceContext(
                workspace_id=workspace.id,
                member_id=None,
                role="admin",
            ),
            cipher=cipher,
        ).save(
            provider="openai_compatible",
            display_name="分析模型",
            model_id="example-chat",
            base_url="https://api.example.com/v1",
            capabilities=frozenset({Capability.TEXT}),
            status=AdapterStatus.COMMUNITY,
            api_key="synthetic-key-never-real",
        )

        config_id, binding = resolve_analysis_model_binding(
            session=session,
            context=WorkspaceContext(
                workspace_id=workspace.id,
                member_id=None,
                role="editor",
            ),
            cipher=cipher,
            mock_mode=False,
        )

        assert config_id == config.id
        assert binding.provider == "openai_compatible"
        assert binding.contract_version == "openai-compatible-chat-json-v1"
