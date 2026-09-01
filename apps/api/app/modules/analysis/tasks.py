from typing import Literal, cast
from uuid import UUID

from celery import shared_task  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.core.logging import current_request_id, task_request_context
from app.core.observability import record_task_correlation
from app.modules.analysis.features import AnalysisEvidenceBundle
from app.modules.analysis.models import AnalysisRun
from app.modules.analysis.schemas import (
    AnalysisAdapter,
    InvalidAnalysisOutput,
    MockAnalysisAdapter,
)
from app.modules.analysis.service import (
    begin_analysis_attempt,
    lease_recoverable_analysis_runs,
    persist_analysis_failure,
    persist_analysis_success,
    record_analysis_processing_started,
    record_analysis_provider_failure,
)
from app.modules.content.models import Content
from app.modules.models.adapter_factory import (
    ModelBinding,
    ModelSelectionError,
    UsageGovernanceContext,
    create_workspace_model_adapter,
)
from app.modules.models.adapters.qianwen_analysis import (
    QianwenAnalysisAdapter,
    StructuredAnalysisProvider,
)
from app.modules.models.adapters.qianwen import (
    ModelProviderError,
    safe_model_error_message,
)
from app.modules.models.capabilities import Capability
from app.modules.models.config_service import SecretCipher
from app.modules.models.usage import ProviderOperation


def build_analysis_adapter_for_run(
    *,
    session: Session,
    run: AnalysisRun,
    platform: Literal["douyin", "xiaohongshu"],
    cipher: SecretCipher,
    mock_mode: bool,
) -> AnalysisAdapter:
    if mock_mode:
        return MockAnalysisAdapter()
    if run.model_config_id is None:
        raise ModelSelectionError(
            "MODEL_CONFIGURATION_REQUIRED",
            "模型配置不可用，请重新创建任务。",
        )
    expected = ModelBinding(
        provider=run.model_provider,
        model_id=run.model_version,
        contract_version=run.provider_contract_version,
        configuration_version=run.model_config_version,
    )
    settings = get_settings()
    bound = create_workspace_model_adapter(
        session=session,
        workspace_id=run.workspace_id,
        model_config_id=run.model_config_id,
        required_capability=Capability.TEXT,
        cipher=cipher,
        mock_mode=False,
        expected=expected,
        usage_context=UsageGovernanceContext(
            session_factory=SessionFactory,
            redis_url=settings.redis_url,
            actor_id=run.requested_by,
            task_id=run.id,
            operation=ProviderOperation.ANALYSIS,
        ),
    )
    if bound.binding.provider != "qianwen":
        raise ModelSelectionError(
            "MODEL_CAPABILITY_UNAVAILABLE",
            "固定模型 Provider 不受支持。",
        )
    return QianwenAnalysisAdapter(
        cast(StructuredAnalysisProvider, bound.adapter),
        platform=platform,
        model_version=bound.binding.model_id,
    )


def enqueue_analysis(run_id: UUID) -> None:
    request_id = current_request_id()
    if get_settings().run_tasks_inline:
        analyze_content_task(str(run_id), request_id)
    else:
        analyze_content_task.delay(str(run_id), request_id)


def get_analysis_enqueuer():
    return enqueue_analysis


def get_auto_analysis_enqueuer():
    return enqueue_analysis


@shared_task(name="analysis.analyze_content")
def analyze_content_task(run_id: str, request_id: str | None = None) -> None:
    with task_request_context(request_id) as safe_request_id:
        settings = get_settings()
        parsed_run_id = UUID(run_id)
        with SessionFactory() as session:
            run = session.get(AnalysisRun, parsed_run_id)
            if run is not None:
                record_task_correlation(
                    session,
                    workspace_id=run.workspace_id,
                    task_id=run.id,
                    task_type="analysis",
                    request_id=safe_request_id,
                )
            should_process = begin_analysis_attempt(session, parsed_run_id)
            session.commit()
        if not should_process:
            return
        try:
            with SessionFactory() as session:
                run = session.get(AnalysisRun, parsed_run_id)
                if run is None:
                    return
                platform = session.scalar(
                    select(Content.platform).where(
                        Content.id == run.content_id,
                        Content.workspace_id == run.workspace_id,
                        Content.account_id == run.account_id,
                    )
                )
                if platform is None:
                    raise ModelSelectionError(
                        "MODEL_CONFIGURATION_REQUIRED",
                        "分析内容不可用，请重新创建任务。",
                    )
                adapter = build_analysis_adapter_for_run(
                    session=session,
                    run=run,
                    platform=cast(
                        Literal["douyin", "xiaohongshu"],
                        platform.value,
                    ),
                    cipher=SecretCipher(
                        settings.model_secret_encryption_key.get_secret_value()
                    ),
                    mock_mode=settings.app_mock_mode,
                )
                bundle = AnalysisEvidenceBundle.model_validate(
                    run.evidence_bundle
                )
                record_analysis_processing_started(session, run)
                session.commit()
        except ModelSelectionError as error:
            with SessionFactory() as session:
                persist_analysis_failure(
                    session,
                    parsed_run_id,
                    error_code=error.code,
                    error_message=str(error),
                )
                session.commit()
            return
        except Exception:
            with SessionFactory() as session:
                record_analysis_provider_failure(session, parsed_run_id)
                session.commit()
            return
        try:
            report = adapter.analyze(bundle)
            report.validate_references(bundle)
        except ModelProviderError as error:
            with SessionFactory() as session:
                persist_analysis_failure(
                    session,
                    parsed_run_id,
                    error_code=error.code.value,
                    error_message=safe_model_error_message(error.code),
                )
                session.commit()
        except (InvalidAnalysisOutput, ValueError):
            with SessionFactory() as session:
                persist_analysis_failure(
                    session,
                    parsed_run_id,
                    error_code="MODEL_INVALID_RESPONSE",
                    error_message="模型返回内容未通过结构或证据校验。",
                )
                session.commit()
        except Exception:
            with SessionFactory() as session:
                record_analysis_provider_failure(session, parsed_run_id)
                session.commit()
        else:
            with SessionFactory() as session:
                persist_analysis_success(session, parsed_run_id, report)
                session.commit()


@shared_task(name="analysis.recover_pending")
def recover_pending_analysis_task() -> None:
    with SessionFactory() as session:
        run_ids = lease_recoverable_analysis_runs(session)
        session.commit()
    for run_id in run_ids:
        analyze_content_task.delay(str(run_id), current_request_id())
