import asyncio
from typing import cast
from uuid import UUID

from celery import shared_task  # type: ignore[import-untyped]
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionFactory, utc_now
from app.core.logging import current_request_id, task_request_context
from app.core.observability import record_task_correlation
from app.core.security import WorkspaceContext, WorkspaceRole
from app.core.storage import get_storage
from app.modules.content.models import Content
from app.modules.generation.cover_safety import PersistedCoverSafetyGate
from app.modules.generation.cover_service import (
    CoverGenerationCoordinator,
    CoverImageAdapter,
    MockCoverImageAdapter,
)
from app.modules.generation.models import (
    CoverGenerationStatus,
    CoverGenerationRun,
    TextGenerationRun,
)
from app.modules.imports.vision_binding import (
    create_bound_vision_adapter,
    resolve_vision_binding,
)
from app.modules.generation.schemas import GenerationContext
from app.modules.generation.text_service import (
    begin_text_generation_attempt,
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
from app.modules.models.adapters.qianwen_image import QianwenCoverImageAdapter
from app.modules.models.adapter_factory import (
    ModelBinding,
    ModelSelectionError,
    UsageGovernanceContext,
    create_workspace_model_adapter,
)
from app.modules.models.capabilities import Capability
from app.modules.models.adapters.qianwen import (
    ModelProviderError,
    safe_model_error_message,
)
from app.modules.models.config_service import SecretCipher
from app.modules.models.catalog import QianwenRegion, get_catalog_entry
from app.modules.models.config_service import model_configuration_version
from app.modules.models.models import ModelConfig, ModelConfigStatus
from app.modules.models.usage import (
    ProviderOperation,
    create_model_usage_governor,
)
from app.modules.workspace.models import WorkspaceMember


def build_cover_adapter_for_run(
    *,
    session: Session,
    run: CoverGenerationRun,
    cipher: SecretCipher,
    mock_mode: bool,
) -> CoverImageAdapter:
    if run.provider == "template" or mock_mode:
        return MockCoverImageAdapter()
    if run.provider != "qianwen" or run.model_config_id is None:
        raise ModelSelectionError(
            "MODEL_CAPABILITY_UNAVAILABLE",
            "固定图片模型 Provider 不受支持。",
        )
    config = session.scalar(
        select(ModelConfig).where(
            ModelConfig.id == run.model_config_id,
            ModelConfig.workspace_id == run.workspace_id,
            ModelConfig.status != ModelConfigStatus.INCOMPATIBLE,
        )
    )
    if (
        config is None
        or config.provider != run.provider
        or config.model_id != run.model_id
        or config.region != run.region
        or config.region is None
        or config.encryption_key_version != cipher.version
        or model_configuration_version(config)
        != run.configuration_version
    ):
        raise ModelSelectionError(
            "MODEL_CONFIGURATION_REQUIRED",
            "固定图片模型配置不可用，请重新创建任务。",
        )
    catalog = get_catalog_entry(config.provider, config.model_id)
    if (
        Capability.IMAGE not in catalog.capabilities
        or Capability.IMAGE.value not in config.capabilities
        or catalog.contract_version != run.contract_version
    ):
        raise ModelSelectionError(
            "MODEL_CAPABILITY_UNAVAILABLE",
            "固定图片模型能力当前不可用。",
        )
    try:
        raw_references = run.request_json.get("references", [])
        references = (
            raw_references if isinstance(raw_references, list) else []
        )
        has_provider_reference = any(
            isinstance(reference, dict)
            and reference.get("provider_input") is True
            for reference in references
        )
        return QianwenCoverImageAdapter(
            api_key=SecretStr(cipher.decrypt(config.encrypted_api_key)),
            region=QianwenRegion(config.region),
            provider_workspace_id=config.provider_workspace_id,
            model_id=config.model_id,
            usage_governor=create_model_usage_governor(
                session_factory=SessionFactory,
                redis_url=get_settings().redis_url,
                workspace_id=run.workspace_id,
                model_config=config,
                actor_id=run.requested_by,
                task_id=run.id,
                capability=Capability.IMAGE,
                operation=(
                    ProviderOperation.COVER_IMAGE_EDIT
                    if has_provider_reference
                    else ProviderOperation.COVER_TEXT_TO_IMAGE
                ),
                contract_version=run.contract_version,
                configuration_version=run.configuration_version,
            ),
        )
    except ValueError as error:
        raise ModelSelectionError(
            "MODEL_CONFIGURATION_REQUIRED",
            "固定图片模型配置不可用，请重新创建任务。",
        ) from error


def enqueue_cover_generation(run_id: UUID) -> None:
    settings = get_settings()
    request_id = current_request_id()
    if settings.app_mock_mode:
        generate_cover_task(str(run_id), request_id)
    else:
        generate_cover_task.delay(str(run_id), request_id)


def get_cover_generation_enqueuer():
    return enqueue_cover_generation


@shared_task(name="generation.generate_cover")
def generate_cover_task(
    run_id: str,
    request_id: str | None = None,
) -> None:
    """Run one non-idempotent Provider attempt without Celery auto-retry."""
    parsed_id = UUID(run_id)
    with task_request_context(request_id) as safe_request_id:
        settings = get_settings()
        cipher = SecretCipher(
            settings.model_secret_encryption_key.get_secret_value()
        )
        with SessionFactory() as session:
            run = session.get(CoverGenerationRun, parsed_id)
            if run is None:
                return
            member = session.scalar(
                select(WorkspaceMember).where(
                    WorkspaceMember.id == run.requested_by,
                    WorkspaceMember.workspace_id == run.workspace_id,
                    WorkspaceMember.revoked_at.is_(None),
                )
            )
            content = session.scalar(
                select(Content).where(
                    Content.id == run.content_id,
                    Content.workspace_id == run.workspace_id,
                )
            )
            if member is None or content is None:
                run.status = CoverGenerationStatus.FAILED
                run.error_code = "MODEL_CONFIGURATION_REQUIRED"
                run.status_detail = "封面任务成员或内容已失效。"
                run.completed_at = utc_now()
                session.commit()
                return
            record_task_correlation(
                session,
                workspace_id=run.workspace_id,
                task_id=run.id,
                task_type="cover_generation",
                request_id=safe_request_id,
            )
            context = WorkspaceContext(
                workspace_id=run.workspace_id,
                member_id=member.id,
                role=cast(WorkspaceRole, member.role.value),
            )
            try:
                adapter = build_cover_adapter_for_run(
                    session=session,
                    run=run,
                    cipher=cipher,
                    mock_mode=settings.app_mock_mode,
                )
            except ModelSelectionError as error:
                run.status = CoverGenerationStatus.FAILED
                run.error_code = error.code
                run.status_detail = str(error)
                run.completed_at = utc_now()
                session.commit()
                return
            try:
                vision_binding = resolve_vision_binding(
                    session,
                    context,
                    platform=content.platform,
                    content_type=content.content_type,
                    cipher=cipher,
                    mock_mode=settings.app_mock_mode,
                )
                vision_config = (
                    session.get(
                        ModelConfig,
                        vision_binding.model_config_id,
                    )
                    if vision_binding.model_config_id is not None
                    else None
                )
                vision_adapter = create_bound_vision_adapter(
                    session,
                    workspace_id=run.workspace_id,
                    expected_platform=content.platform,
                    binding=vision_binding,
                    cipher=cipher,
                    mock_mode=settings.app_mock_mode,
                    usage_governor=(
                        create_model_usage_governor(
                            session_factory=SessionFactory,
                            redis_url=settings.redis_url,
                            workspace_id=run.workspace_id,
                            model_config=vision_config,
                            actor_id=run.requested_by,
                            task_id=run.id,
                            capability=Capability.VISION,
                            operation=ProviderOperation.OCR,
                            contract_version=(
                                vision_binding.contract_version
                            ),
                            configuration_version=(
                                vision_binding.config_version
                            ),
                        )
                        if not settings.app_mock_mode
                        and vision_config is not None
                        else None
                    ),
                )
            except (LookupError, ValueError):
                vision_adapter = None
            account_id = run.account_id
            title = content.title
            body = content.body
            session.commit()
        gate = PersistedCoverSafetyGate(
            SessionFactory,
            context=context,
            account_id=account_id,
            title=title,
            body=body,
            vision_adapter=vision_adapter,
        )
        try:
            CoverGenerationCoordinator(
                SessionFactory,
                context=context,
            ).run(
                parsed_id,
                adapter=adapter,
                storage=get_storage(),
                safety_gate=gate,
            )
        except Exception:
            # The coordinator records a stable, safe state. Celery must not
            # retry a possibly billed image request automatically.
            return


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
    settings = get_settings()
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
        usage_context=UsageGovernanceContext(
            session_factory=SessionFactory,
            redis_url=settings.redis_url,
            actor_id=run.requested_by,
            task_id=run.id,
            operation=ProviderOperation.TEXT_GENERATION,
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
                should_process = begin_text_generation_attempt(
                    session,
                    parsed_id,
                )
                session.commit()
            if run is None or not should_process:
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
