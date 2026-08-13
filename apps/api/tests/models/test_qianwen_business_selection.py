from uuid import uuid4
from pathlib import Path

import httpx
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.config import Settings
from app.modules.models.capabilities import (
    AdapterStatus,
    Capability,
    ModelRequest,
)
from app.modules.models.adapters.qianwen import (
    ModelErrorCode,
    ModelProviderError,
)
from app.modules.models.catalog import QIANWEN_TEXT_MODEL_ID, QianwenRegion
from app.modules.models.config_service import ModelConfigService, SecretCipher
from app.modules.models.models import ModelConfigStatus
from app.modules.workspace.models import Workspace
from app.core.security import WorkspaceContext


class CountingCipher(SecretCipher):
    def __init__(self) -> None:
        super().__init__("task-2-factory-synthetic-encryption-key")
        self.decrypt_calls = 0

    def decrypt(self, value: str) -> str:
        self.decrypt_calls += 1
        return super().decrypt(value)


def _session_and_config() -> tuple[Session, Workspace, object, CountingCipher]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    workspace = Workspace(name="Task 2 Factory 合成工作区")
    session.add(workspace)
    session.flush()
    cipher = CountingCipher()
    config = ModelConfigService(
        session,
        WorkspaceContext(
            workspace_id=workspace.id,
            member_id=None,
            role="admin",
        ),
        cipher=cipher,
    ).save(
        provider="qianwen",
        model_id=QIANWEN_TEXT_MODEL_ID,
        capabilities=frozenset({Capability.TEXT}),
        status=AdapterStatus.EXPERIMENTAL,
        api_key="sk-task-2-synthetic-never-real",
        region=QianwenRegion.CN_BEIJING,
        provider_workspace_id="llm-task2",
    )
    return session, workspace, config, cipher


def test_factory_binds_exact_workspace_catalog_and_decrypts_once_at_call_boundary() -> None:
    from app.modules.models.adapter_factory import (
        ModelBinding,
        create_workspace_model_adapter,
    )
    from app.modules.models.config_service import model_configuration_version

    session, workspace, config, cipher = _session_and_config()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"value":"safe"}'},
                    }
                ]
            },
        )

    bound = create_workspace_model_adapter(
        session=session,
        workspace_id=workspace.id,
        model_config_id=config.id,
        required_capability=Capability.TEXT,
        cipher=cipher,
        mock_mode=False,
        expected=ModelBinding(
            provider="qianwen",
            model_id=QIANWEN_TEXT_MODEL_ID,
            contract_version="qianwen-chat-json-v1",
            configuration_version=model_configuration_version(config),
        ),
        transport=httpx.MockTransport(handler),
    )

    assert bound.binding.provider == "qianwen"
    assert bound.binding.model_id == QIANWEN_TEXT_MODEL_ID
    assert cipher.decrypt_calls == 1
    assert calls == 0
    session.close()


def test_mock_mode_never_queries_or_decrypts_qianwen_credentials() -> None:
    from app.modules.models.adapter_factory import (
        ModelBinding,
        create_workspace_model_adapter,
    )

    session, workspace, config, cipher = _session_and_config()
    session.delete(config)
    session.flush()

    bound = create_workspace_model_adapter(
        session=session,
        workspace_id=workspace.id,
        model_config_id=uuid4(),
        required_capability=Capability.TEXT,
        cipher=cipher,
        mock_mode=True,
        expected=ModelBinding(
            provider="mock",
            model_id="mock-v1",
            contract_version="mock-structured-v1",
        ),
    )

    assert bound.binding.provider == "mock"
    assert cipher.decrypt_calls == 0
    session.close()


def test_cross_workspace_or_changed_binding_fails_without_secret_decryption() -> None:
    from app.modules.models.adapter_factory import (
        ModelBinding,
        ModelSelectionError,
        create_workspace_model_adapter,
    )

    session, _, config, cipher = _session_and_config()
    other_workspace = Workspace(name="其他工作区")
    session.add(other_workspace)
    session.flush()

    for workspace_id, expected in (
        (
            other_workspace.id,
            ModelBinding(
                provider="qianwen",
                model_id=QIANWEN_TEXT_MODEL_ID,
                contract_version="qianwen-chat-json-v1",
            ),
        ),
        (
            config.workspace_id,
            ModelBinding(
                provider="qianwen",
                model_id="qwen-changed",
                contract_version="qianwen-chat-json-v1",
            ),
        ),
    ):
        try:
            create_workspace_model_adapter(
                session=session,
                workspace_id=workspace_id,
                model_config_id=config.id,
                required_capability=Capability.TEXT,
                cipher=cipher,
                mock_mode=False,
                expected=expected,
            )
        except ModelSelectionError as error:
            assert error.code == "MODEL_CONFIGURATION_REQUIRED"
            assert "qwen" not in str(error)
        else:
            raise AssertionError("unsafe model selection must fail")

    assert cipher.decrypt_calls == 0
    session.close()


def test_changed_config_version_is_rejected_before_decryption() -> None:
    from app.modules.models.adapter_factory import (
        ModelBinding,
        ModelSelectionError,
        create_workspace_model_adapter,
    )

    session, workspace, config, cipher = _session_and_config()
    frozen_version = config.updated_at.isoformat()
    config.provider_workspace_id = "llm-changed"
    session.flush()
    assert config.updated_at.isoformat() != frozen_version

    with pytest.raises(ModelSelectionError) as caught:
        create_workspace_model_adapter(
            session=session,
            workspace_id=workspace.id,
            model_config_id=config.id,
            required_capability=Capability.TEXT,
            cipher=cipher,
            mock_mode=False,
            expected=ModelBinding(
                provider="qianwen",
                model_id=QIANWEN_TEXT_MODEL_ID,
                contract_version="qianwen-chat-json-v1",
                configuration_version=frozen_version,
            ),
        )

    assert caught.value.code == "MODEL_CONFIGURATION_REQUIRED"
    assert cipher.decrypt_calls == 0
    session.close()


def test_disabled_qianwen_config_is_not_replaced_or_decrypted() -> None:
    from app.modules.models.adapter_factory import (
        ModelBinding,
        ModelSelectionError,
        create_workspace_model_adapter,
    )

    session, workspace, config, cipher = _session_and_config()
    config.status = ModelConfigStatus.INCOMPATIBLE
    session.flush()

    try:
        create_workspace_model_adapter(
            session=session,
            workspace_id=workspace.id,
            model_config_id=config.id,
            required_capability=Capability.TEXT,
            cipher=cipher,
            mock_mode=False,
            expected=ModelBinding(
                provider="qianwen",
                model_id=QIANWEN_TEXT_MODEL_ID,
                contract_version="qianwen-chat-json-v1",
            ),
        )
    except ModelSelectionError as error:
        assert error.code == "MODEL_CAPABILITY_UNAVAILABLE"
    else:
        raise AssertionError("disabled config must not be used")

    assert cipher.decrypt_calls == 0
    session.close()


def test_generation_persists_provider_error_without_mock_fallback() -> None:
    from app.modules.generation.models import TextGenerationRunStatus
    from app.modules.generation.text_service import (
        create_text_generation,
        process_text_generation,
    )
    from tests.generation.test_text_generation import _context

    class AuthenticationFailure:
        async def generate(self, request):
            raise ModelProviderError(ModelErrorCode.AUTHENTICATION_FAILED)

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        run, _ = create_text_generation(session, _context())

        failed = process_text_generation(
            session,
            run.id,
            adapter=AuthenticationFailure(),
        )

        assert failed.status is TextGenerationRunStatus.FAILED
        assert failed.error_code == "MODEL_AUTHENTICATION_FAILED"
        assert failed.status_detail == "模型鉴权失败，请管理员检查模型配置。"
        assert failed.original_result is None


def test_analysis_binding_versions_isolate_cache_and_persist_on_run() -> None:
    from app.modules.analysis.models import AnalysisRunStatus
    from app.modules.analysis.schemas import MockAnalysisAdapter
    from app.modules.analysis.service import (
        AnalysisVersionContext,
        execute_bundle_analysis,
    )
    from tests.analysis.test_analysis_cache import evidence_bundle

    bundle = evidence_bundle()
    common = {
        "workspace_id": uuid4(),
        "account_id": uuid4(),
        "content_id": bundle.content.id,
        "benchmark_run_id": bundle.benchmark.id,
        "snapshot_ids": [item.id for item in bundle.snapshots],
        "model_config_id": uuid4(),
        "model_provider": "qianwen",
        "model_version": QIANWEN_TEXT_MODEL_ID,
        "provider_contract_version": "qianwen-chat-json-v1",
        "model_config_version": "2026-07-28T01:02:03+00:00",
        "prompt_version": "analysis-prompt-v1",
        "algorithm_version": "analysis-v1",
        "benchmark_algorithm_version": "benchmark-v1",
        "trigger_kind": "manual",
    }
    first_context = AnalysisVersionContext(**common)
    second_context = first_context.model_copy(
        update={"provider_contract_version": "qianwen-chat-json-v2"}
    )
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine, expire_on_commit=False) as session:
        first = execute_bundle_analysis(
            session,
            bundle,
            first_context,
            MockAnalysisAdapter(),
        )
        second = execute_bundle_analysis(
            session,
            bundle,
            second_context,
            MockAnalysisAdapter(),
        )

        assert first.status is AnalysisRunStatus.SUCCEEDED
        assert second.id != first.id
        assert first.model_config_id == first_context.model_config_id
        assert first.model_provider == "qianwen"
        assert first.provider_contract_version == "qianwen-chat-json-v1"
        assert first.cache_key != second.cache_key


def test_analysis_persists_provider_error_and_does_not_save_report() -> None:
    from app.modules.analysis.models import AnalysisRunStatus
    from app.modules.analysis.service import (
        AnalysisVersionContext,
        execute_bundle_analysis,
    )
    from tests.analysis.test_analysis_cache import evidence_bundle

    class RateLimitedAdapter:
        model_version = QIANWEN_TEXT_MODEL_ID

        def analyze(self, bundle):
            raise ModelProviderError(ModelErrorCode.RATE_LIMITED)

    bundle = evidence_bundle()
    context = AnalysisVersionContext(
        workspace_id=uuid4(),
        account_id=uuid4(),
        content_id=bundle.content.id,
        benchmark_run_id=bundle.benchmark.id,
        snapshot_ids=[item.id for item in bundle.snapshots],
        model_config_id=uuid4(),
        model_provider="qianwen",
        model_version=QIANWEN_TEXT_MODEL_ID,
        provider_contract_version="qianwen-chat-json-v1",
        prompt_version="analysis-prompt-v1",
        algorithm_version="analysis-v1",
        benchmark_algorithm_version="benchmark-v1",
        trigger_kind="manual",
    )
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine, expire_on_commit=False) as session:
        failed = execute_bundle_analysis(
            session,
            bundle,
            context,
            RateLimitedAdapter(),
        )

        assert failed.status is AnalysisRunStatus.FAILED
        assert failed.error_code == "MODEL_RATE_LIMITED"
        assert failed.error_message == "模型请求受限，请稍后重新创建分析任务。"
        assert failed.report is None


def test_generation_context_freezes_provider_contract_and_cache_identity() -> None:
    from app.modules.generation.schemas import ModelSnapshot
    from app.modules.generation.text_service import text_generation_cache_key
    from tests.generation.test_text_generation import _context

    qianwen = ModelSnapshot(
        config_id=uuid4(),
        provider="qianwen",
        model_id=QIANWEN_TEXT_MODEL_ID,
        capabilities=("text",),
        status="experimental",
        contract_version="qianwen-chat-json-v1",
        configuration_version="2026-07-28T01:02:03+00:00",
    )
    first = _context().model_copy(update={"model": qianwen})
    second = first.model_copy(
        update={
            "model": qianwen.model_copy(
                update={"configuration_version": "changed-version"}
            )
        }
    )

    assert first.model.contract_version == "qianwen-chat-json-v1"
    assert text_generation_cache_key(first) != text_generation_cache_key(second)


def test_analysis_request_selection_uses_current_workspace_text_config() -> None:
    from app.modules.analysis.service import resolve_analysis_model_binding

    session, workspace, config, cipher = _session_and_config()
    other_workspace = Workspace(name="不可见模型工作区")
    session.add(other_workspace)
    session.flush()
    other_config = ModelConfigService(
        session,
        WorkspaceContext(
            workspace_id=other_workspace.id,
            member_id=None,
            role="admin",
        ),
        cipher=cipher,
    ).save(
        provider="qianwen",
        model_id=QIANWEN_TEXT_MODEL_ID,
        capabilities=frozenset({Capability.TEXT}),
        status=AdapterStatus.EXPERIMENTAL,
        api_key="sk-other-workspace-synthetic",
        region=QianwenRegion.CN_BEIJING,
        provider_workspace_id="llm-other",
    )

    selected_id, binding = resolve_analysis_model_binding(
        session=session,
        context=WorkspaceContext(
            workspace_id=workspace.id,
            member_id=None,
            role="editor",
        ),
        cipher=cipher,
        mock_mode=False,
    )

    assert selected_id == config.id
    assert selected_id != other_config.id
    assert binding.provider == "qianwen"
    assert binding.model_id == QIANWEN_TEXT_MODEL_ID
    assert binding.contract_version == "qianwen-chat-json-v1"
    assert binding.configuration_version == config.updated_at.isoformat()
    assert cipher.decrypt_calls == 0
    session.close()


def test_non_mock_analysis_selection_ignores_coexisting_mock_config() -> None:
    from app.modules.analysis.service import resolve_analysis_model_binding

    session, workspace, qianwen_config, cipher = _session_and_config()
    ModelConfigService(
        session,
        WorkspaceContext(
            workspace_id=workspace.id,
            member_id=None,
            role="admin",
        ),
        cipher=cipher,
    ).save(
        provider="mock",
        model_id="mock-v1",
        capabilities=frozenset({Capability.TEXT}),
        status=AdapterStatus.VERIFIED,
        api_key="mock-does-not-leave-process",
    )

    selected_id, binding = resolve_analysis_model_binding(
        session=session,
        context=WorkspaceContext(
            workspace_id=workspace.id,
            member_id=None,
            role="editor",
        ),
        cipher=cipher,
        mock_mode=False,
    )

    assert selected_id == qianwen_config.id
    assert binding.provider == "qianwen"
    assert cipher.decrypt_calls == 0
    session.close()


def test_analysis_mock_selection_does_not_require_model_config() -> None:
    from app.modules.analysis.service import resolve_analysis_model_binding

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        workspace = Workspace(name="Mock 分析工作区")
        session.add(workspace)
        session.flush()
        cipher = CountingCipher()

        selected_id, binding = resolve_analysis_model_binding(
            session=session,
            context=WorkspaceContext(
                workspace_id=workspace.id,
                member_id=None,
                role="editor",
            ),
            cipher=cipher,
            mock_mode=True,
        )

        assert selected_id is None
        assert binding.provider == "mock"
        assert binding.model_id == "mock-analysis-v1"
        assert cipher.decrypt_calls == 0


def test_generation_worker_adapter_uses_frozen_run_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.generation.models import TextGenerationRun
    from app.modules.generation.schemas import ModelSnapshot
    from app.modules.generation.tasks import build_text_adapter_for_run
    from app.modules.generation.text_service import GeneratedTextDraft
    from app.modules.models.adapter_factory import BoundModelAdapter, ModelBinding
    from tests.generation.test_text_generation import _context

    class FakeProvider:
        async def generate_structured(self, request: ModelRequest):
            return GeneratedTextDraft(
                titles=("标题一", "标题二", "标题三"),
                copy="合成文案",
                claims=(),
            )

    expected = ModelBinding(
        provider="qianwen",
        model_id=QIANWEN_TEXT_MODEL_ID,
        contract_version="qianwen-chat-json-v1",
        configuration_version="2026-07-28T01:02:03+00:00",
    )
    captured: dict[str, object] = {}

    def fake_factory(**kwargs):
        captured.update(kwargs)
        return BoundModelAdapter(adapter=FakeProvider(), binding=expected)

    import app.modules.generation.tasks as generation_tasks

    monkeypatch.setattr(
        generation_tasks,
        "create_workspace_model_adapter",
        fake_factory,
    )
    context = _context().model_copy(
        update={
            "model": ModelSnapshot(
                config_id=uuid4(),
                provider=expected.provider,
                model_id=expected.model_id,
                capabilities=("text",),
                status="experimental",
                contract_version=expected.contract_version,
                configuration_version=expected.configuration_version,
            )
        }
    )
    run = TextGenerationRun(
        workspace_id=context.workspace_id,
        account_id=context.account_id,
        model_config_id=context.model.config_id,
        cache_key="a" * 64,
        context=context.model_dump(mode="json"),
        status="queued",
    )
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        adapter = build_text_adapter_for_run(
            session=session,
            run=run,
            cipher=CountingCipher(),
            mock_mode=False,
        )

    assert adapter is not None
    assert captured["workspace_id"] == context.workspace_id
    assert captured["model_config_id"] == context.model.config_id
    assert captured["required_capability"] is Capability.TEXT
    assert captured["expected"] == expected


def test_analysis_worker_adapter_uses_frozen_run_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.analysis.models import AnalysisRun
    from app.modules.analysis.schemas import AnalysisReport, MockAnalysisAdapter
    from app.modules.analysis.tasks import build_analysis_adapter_for_run
    from app.modules.models.adapter_factory import BoundModelAdapter, ModelBinding
    from tests.analysis.test_analysis_report import evidence_bundle

    bundle = evidence_bundle()
    expected = ModelBinding(
        provider="qianwen",
        model_id=QIANWEN_TEXT_MODEL_ID,
        contract_version="qianwen-chat-json-v1",
        configuration_version="2026-07-28T01:02:03+00:00",
    )

    class FakeProvider:
        async def generate_structured(
            self,
            request: ModelRequest[AnalysisReport],
        ) -> AnalysisReport:
            return MockAnalysisAdapter().analyze(bundle)

    captured: dict[str, object] = {}

    def fake_factory(**kwargs):
        captured.update(kwargs)
        return BoundModelAdapter(adapter=FakeProvider(), binding=expected)

    import app.modules.analysis.tasks as analysis_tasks

    monkeypatch.setattr(
        analysis_tasks,
        "create_workspace_model_adapter",
        fake_factory,
    )
    run = AnalysisRun(
        workspace_id=uuid4(),
        account_id=uuid4(),
        content_id=bundle.content.id,
        benchmark_run_id=bundle.benchmark.id,
        snapshot_ids=[str(item.id) for item in bundle.snapshots],
        status="pending",
        trigger_kind="manual",
        cache_key="b" * 64,
        evidence_bundle=bundle.model_dump(mode="json"),
        model_config_id=uuid4(),
        model_provider=expected.provider,
        model_version=expected.model_id,
        provider_contract_version=expected.contract_version,
        model_config_version=expected.configuration_version,
        prompt_version="analysis-prompt-v1",
        algorithm_version="analysis-v1",
        benchmark_algorithm_version="benchmark-v1",
    )
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        adapter = build_analysis_adapter_for_run(
            session=session,
            run=run,
            platform="douyin",
            cipher=CountingCipher(),
            mock_mode=False,
        )

    assert adapter.model_version == QIANWEN_TEXT_MODEL_ID
    assert captured["workspace_id"] == run.workspace_id
    assert captured["model_config_id"] == run.model_config_id
    assert captured["expected"] == expected


def test_analysis_model_binding_migration_is_current_head() -> None:
    root = Path(__file__).parents[4]
    config = Config(str(root / "apps" / "api" / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_current_head() == "20260813_0042"


def test_non_mock_analysis_api_requires_workspace_text_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.analysis.service as analysis_service
    from tests.imports.helpers import (
        configured_client,
        create_published_content,
        create_workspace_account,
    )

    monkeypatch.setattr(
        analysis_service,
        "get_settings",
        lambda: Settings(app_mock_mode=False),
    )
    with configured_client() as (client, _):
        workspace_id, csrf, account = create_workspace_account(client)
        content = create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="无模型配置合成内容",
            work_url="https://example.test/no-model-config",
        )
        snapshot = client.post(
            f"/v1/contents/{content['id']}/snapshots",
            headers={"X-CSRF-Token": csrf},
            json={
                "collected_at": content["published_at"],
                "source": "manual",
                "metrics": [{"key": "views", "raw_value": 120}],
            },
        ).json()
        client.post(
            f"/v1/contents/{content['id']}/snapshots/{snapshot['id']}/confirm",
            headers={"X-CSRF-Token": csrf},
        )

        response = client.post(
            f"/v1/contents/{content['id']}/analysis-runs",
            headers={"X-CSRF-Token": csrf},
        )

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == (
            "MODEL_CONFIGURATION_REQUIRED"
        )
        assert "api_key" not in response.text


def test_non_mock_analysis_api_freezes_qianwen_binding_on_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.analysis.service as analysis_service
    from app.main import app
    from app.modules.analysis.tasks import get_analysis_enqueuer
    from tests.imports.helpers import (
        configured_client,
        create_published_content,
        create_workspace_account,
    )

    monkeypatch.setattr(
        analysis_service,
        "get_settings",
        lambda: Settings(app_mock_mode=False),
    )
    enqueued: list[object] = []
    with configured_client() as (client, _):
        app.dependency_overrides[get_analysis_enqueuer] = lambda: enqueued.append
        workspace_id, csrf, account = create_workspace_account(client)
        config_response = client.post(
            f"/v1/workspaces/{workspace_id}/model-configs",
            headers={"X-CSRF-Token": csrf},
            json={
                "provider": "qianwen",
                "model_id": QIANWEN_TEXT_MODEL_ID,
                "region": "cn-beijing",
                "provider_workspace_id": "llm-task2api",
                "capabilities": ["text"],
                "status": "experimental",
                "api_key": "sk-task-2-api-synthetic-never-real",
            },
        )
        assert config_response.status_code == 201
        content = create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="固定千问配置合成内容",
            work_url="https://example.test/qianwen-binding",
        )
        snapshot = client.post(
            f"/v1/contents/{content['id']}/snapshots",
            headers={"X-CSRF-Token": csrf},
            json={
                "collected_at": content["published_at"],
                "source": "manual",
                "metrics": [{"key": "views", "raw_value": 180}],
            },
        ).json()
        client.post(
            f"/v1/contents/{content['id']}/snapshots/{snapshot['id']}/confirm",
            headers={"X-CSRF-Token": csrf},
        )

        response = client.post(
            f"/v1/contents/{content['id']}/analysis-runs",
            headers={"X-CSRF-Token": csrf},
        )

        assert response.status_code == 202, response.text
        run = response.json()
        assert run["model_config_id"] == config_response.json()["id"]
        assert run["model_provider"] == "qianwen"
        assert run["model_version"] == QIANWEN_TEXT_MODEL_ID
        assert run["provider_contract_version"] == "qianwen-chat-json-v1"
        assert run["model_config_version"]
        assert "provider_workspace_id" not in response.text
        assert "api_key" not in response.text
        assert len(enqueued) == 1


def test_generation_run_caps_provider_http_attempts_at_two() -> None:
    from app.modules.generation.models import TextGenerationRunStatus
    from app.modules.generation.text_service import (
        create_text_generation,
        process_text_generation,
    )
    from app.modules.models.adapters.qianwen import QianwenProvider
    from app.modules.models.adapters.qianwen_text_generation import (
        QianwenTextGenerationAdapter,
    )
    from tests.generation.test_text_generation import _context

    calls = 0

    def unavailable(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"message": "never expose"})

    async def no_sleep(delay: float) -> None:
        return None

    adapter = QianwenTextGenerationAdapter(
        QianwenProvider(
            api_key=SecretStr("sk-attempt-cap-synthetic"),
            region=QianwenRegion.CN_BEIJING,
            provider_workspace_id="llm-attempts",
            transport=httpx.MockTransport(unavailable),
            sleeper=no_sleep,
        )
    )
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        run, _ = create_text_generation(session, _context())

        failed = process_text_generation(session, run.id, adapter=adapter)

        assert failed.status is TextGenerationRunStatus.FAILED
        assert failed.error_code == "MODEL_PROVIDER_UNAVAILABLE"
        assert calls == 2


def test_analysis_run_caps_provider_http_attempts_at_two() -> None:
    from app.modules.analysis.models import AnalysisRunStatus
    from app.modules.analysis.service import (
        AnalysisVersionContext,
        execute_bundle_analysis,
    )
    from app.modules.models.adapters.qianwen import QianwenProvider
    from app.modules.models.adapters.qianwen_analysis import (
        QianwenAnalysisAdapter,
    )
    from tests.analysis.test_analysis_cache import evidence_bundle

    calls = 0

    def unavailable(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"message": "never expose"})

    async def no_sleep(delay: float) -> None:
        return None

    bundle = evidence_bundle()
    context = AnalysisVersionContext(
        workspace_id=uuid4(),
        account_id=uuid4(),
        content_id=bundle.content.id,
        benchmark_run_id=bundle.benchmark.id,
        snapshot_ids=[item.id for item in bundle.snapshots],
        model_config_id=uuid4(),
        model_provider="qianwen",
        model_version=QIANWEN_TEXT_MODEL_ID,
        provider_contract_version="qianwen-chat-json-v1",
        model_config_version="2026-07-28T01:02:03+00:00",
        prompt_version="analysis-prompt-v1",
        algorithm_version="analysis-v1",
        benchmark_algorithm_version="benchmark-v1",
        trigger_kind="manual",
    )
    adapter = QianwenAnalysisAdapter(
        QianwenProvider(
            api_key=SecretStr("sk-attempt-cap-synthetic"),
            region=QianwenRegion.CN_BEIJING,
            provider_workspace_id="llm-attempts",
            transport=httpx.MockTransport(unavailable),
            sleeper=no_sleep,
        ),
        platform="douyin",
    )
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        failed = execute_bundle_analysis(
            session,
            bundle,
            context,
            adapter,
        )

        assert failed.status is AnalysisRunStatus.FAILED
        assert failed.error_code == "MODEL_PROVIDER_UNAVAILABLE"
        assert calls == 2
