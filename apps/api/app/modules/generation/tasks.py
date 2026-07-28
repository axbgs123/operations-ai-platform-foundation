import asyncio
from typing import cast
from uuid import UUID

from celery import shared_task  # type: ignore[import-untyped]
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.core.logging import current_request_id, task_request_context
from app.core.observability import record_task_correlation
from app.modules.generation.models import TextGenerationRun, TextGenerationRunStatus
from app.modules.generation.schemas import GenerationContext
from app.modules.generation.text_service import (
    UnsafeGenerationOutput,
    TextGenerationAdapter,
    generate_text,
    persist_text_generation_failure,
    persist_text_generation_success,
)
from app.modules.models.adapters.qianwen_text_generation import (
    QianwenTextGenerationAdapter,
    StructuredTextProvider,
)
from app.modules.models.adapter_factory import (
    ModelBinding,
    ModelSelectionError,
    create_workspace_model_adapter,
)
from app.modules.models.capabilities import Capability
from app.modules.models.adapters.qianwen import (
    ModelProviderError,
    safe_model_error_message,
)
from app.modules.models.config_service import SecretCipher


def build_text_adapter_for_run(
    *,
    session: Session,
    run: TextGenerationRun,
    cipher: SecretCipher,
    mock_mode: bool,
) -> TextGenerationAdapter | None:
    if mock_mode:
        return None
    context = GenerationContext.model_validate(run.context)
    bound = create_workspace_model_adapter(
        session=session,
        workspace_id=run.workspace_id,
        model_config_id=run.model_config_id,
        required_capability=Capability.TEXT,
        cipher=cipher,
        mock_mode=False,
        expected=ModelBinding(
            provider=context.model.provider,
            model_id=context.model.model_id,
            contract_version=context.model.contract_version,
            configuration_version=context.model.configuration_version,
        ),
    )
    if bound.binding.provider != "qianwen":
        raise ModelSelectionError(
            "MODEL_CAPABILITY_UNAVAILABLE",
            "固定模型 Provider 不受支持。",
        )
    return QianwenTextGenerationAdapter(
        cast(StructuredTextProvider, bound.adapter)
    )


def enqueue_text_generation(run_id: UUID) -> None:
    request_id = current_request_id()
    if get_settings().app_mock_mode:
        generate_text_task(str(run_id), request_id)
    else:
        generate_text_task.delay(str(run_id), request_id)


def get_text_generation_enqueuer():
    return enqueue_text_generation


@shared_task(name="generation.generate_text")
def generate_text_task(run_id: str, request_id: str | None = None) -> None:
    with task_request_context(request_id) as safe_request_id:
        settings = get_settings()
        parsed_id = UUID(run_id)
        with SessionFactory() as session:
            run = session.get(TextGenerationRun, parsed_id)
            if run is not None:
                record_task_correlation(
                    session,
                    workspace_id=run.workspace_id,
                    task_id=run.id,
                    task_type="generation",
                    request_id=safe_request_id,
                )
                if run.status == TextGenerationRunStatus.QUEUED:
                    run.status = TextGenerationRunStatus.RUNNING
                session.commit()
            if run is None:
                return
            try:
                adapter = build_text_adapter_for_run(
                    session=session,
                    run=run,
                    cipher=SecretCipher(
                        settings.model_secret_encryption_key.get_secret_value()
                    ),
                    mock_mode=settings.app_mock_mode,
                )
            except ModelSelectionError as error:
                session.rollback()
                persist_text_generation_failure(
                    session,
                    parsed_id,
                    error_code=error.code,
                    status_detail=str(error),
                )
                session.commit()
                return
            context = GenerationContext.model_validate(run.context)
            session.commit()
        try:
            result = asyncio.run(generate_text(context, adapter))
        except UnsafeGenerationOutput:
            code = UnsafeGenerationOutput.code
            detail = "生成内容未通过事实复检，请检查事实后重试。"
        except ModelProviderError as error:
            code = error.code.value
            detail = safe_model_error_message(error.code)
        except (RuntimeError, ValueError):
            code = "MODEL_GENERATION_FAILED"
            detail = "文本模型暂时不可用，请稍后重试。"
        except Exception:
            code = "MODEL_GENERATION_FAILED"
            detail = "文本模型暂时不可用，请稍后重试。"
        else:
            with SessionFactory() as session:
                persist_text_generation_success(
                    session,
                    parsed_id,
                    result,
                    provider_mode=(
                        "mock" if adapter is None else "real"
                    ),
                )
                session.commit()
            return
        with SessionFactory() as session:
            persist_text_generation_failure(
                session,
                parsed_id,
                error_code=code,
                status_detail=detail,
            )
            session.commit()
