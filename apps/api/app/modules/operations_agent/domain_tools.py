from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.security import WorkspaceContext, WorkspaceRole
from app.modules.analysis.features import AnalysisEvidenceBundle
from app.modules.analysis.models import AnalysisRun, AnalysisRunStatus
from app.modules.analysis.schemas import MockAnalysisAdapter
from app.modules.analysis.service import (
    AnalysisService,
    begin_analysis_attempt,
    persist_analysis_terminal_failure,
    persist_analysis_success,
)
from app.modules.analysis.tasks import build_analysis_adapter_for_run
from app.modules.analysis.viral import ViralService
from app.modules.content.account_models import Platform, PlatformAccount
from app.modules.content.models import Content
from app.modules.exports.models import ExportKind
from app.modules.exports.service import create_export_task
from app.modules.generation.context import GenerationContextBuilder
from app.modules.generation.models import (
    TextGenerationRun,
    TextGenerationRunStatus,
)
from app.modules.generation.schemas import (
    GenerationInputs,
    StyleInheritanceSelection,
)
from app.modules.generation.text_service import (
    begin_text_generation_attempt,
    create_text_generation_with_provenance,
    generate_text,
    persist_text_generation_failure,
    persist_text_generation_success,
)
from app.modules.generation.tasks import build_text_adapter_for_run
from app.modules.hotspots.models import HotspotEntry, HotspotSnapshot
from app.modules.hotspots.research import HotspotResearchService
from app.modules.operations_agent.executor import ToolInvocation, ToolObservation
from app.modules.operations_agent.models import (
    AgentArtifact,
    AgentArtifactKind,
    AgentEvent,
    AgentToolRisk,
)
from app.modules.operations_agent.tools import (
    AgentToolContract,
    AgentToolRegistry,
)
from app.modules.models.capabilities import Capability
from app.modules.models.adapters.qianwen import (
    ModelErrorCode,
    ModelProviderError,
    safe_model_error_message,
)
from app.modules.models.config_service import ModelConfigService, SecretCipher
from app.modules.models.models import ModelConfig, ModelConfigStatus
from app.modules.risk_rag.models import RiskScanNode
from app.modules.risk_rag.retrieval import (
    ActiveRiskIndexUnavailable,
    resolve_active_retrieval_filter,
)
from app.modules.risk_rag.scanner import (
    OcrResult,
    OcrStatus,
    RiskScanInput,
    RiskScanService,
    RiskScanVersions,
    build_default_pipeline,
)
from app.modules.style_facts.source_ingestion import FactSourceService
from app.modules.style_facts.style_service import (
    StyleProfileRequired,
    StyleProfileService,
)
from app.modules.workspace.models import WorkspaceMember
from app.modules.workspace.permissions import (
    Permission,
    PermissionDenied,
    require_permission,
)


class ImmutableToolSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AccountToolInput(ImmutableToolSchema):
    account_id: UUID


class ContentToolInput(AccountToolInput):
    content_id: UUID


class ReadConfirmedFactsInput(AccountToolInput):
    confirmed_fact_ids: tuple[UUID, ...] = Field(default=(), max_length=100)


class ReadAccountStyleInput(AccountToolInput):
    column_campaign_id: UUID | None = None


class ReadConfirmedViralAssetsInput(AccountToolInput):
    viral_asset_ids: tuple[UUID, ...] = Field(default=(), max_length=3)


class ReadConfirmedHotspotsInput(AccountToolInput):
    snapshot_id: UUID | None = None


class ResearchConfirmedHotspotInput(AccountToolInput):
    snapshot_id: UUID


class GenerateOptimizationDraftInput(ContentToolInput):
    confirmed_fact_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    style_profile_id: UUID | None = None
    viral_asset_ids: tuple[UUID, ...] = Field(default=(), max_length=3)
    preserve_title_style: bool = True
    preserve_copy_style: bool = True
    preserve_cover_style: bool = True
    user_instruction: str = Field(default="", max_length=20_000)


class DomainToolOutput(ImmutableToolSchema):
    safe_summary: str = Field(min_length=1, max_length=500)
    artifact_refs: tuple[str, ...] = Field(default=(), max_length=32)
    approval_exclusion_refs: tuple[str, ...] = Field(default=(), max_length=32)
    evidence_refs: tuple[str, ...] = Field(default=(), max_length=32)
    publication_performed: Literal[False] = False


class ReadAccountStateOutput(DomainToolOutput):
    account_id: UUID
    content_count: int = Field(ge=0)
    pending_analysis_count: int = Field(ge=0)


class ResourceToolOutput(DomainToolOutput):
    resource_ids: tuple[UUID, ...] = Field(default=(), max_length=100)


class AgentResourceScopeError(LookupError):
    pass


def _contract(
    *,
    name: str,
    risk: AgentToolRisk,
    permission: Permission,
    input_model: type[BaseModel],
    output_model: type[BaseModel] = ResourceToolOutput,
    uses_external_api: bool = False,
    retry_policy: Literal["safe", "never", "manual"] = "safe",
) -> AgentToolContract:
    return AgentToolContract(
        name=name,
        version="1.0.0",
        risk=risk,
        permission=permission,
        uses_external_api=uses_external_api,
        retry_policy=retry_policy,
        input_model=input_model,
        output_model=output_model,
    )


def build_domain_tool_registry() -> AgentToolRegistry:
    return AgentToolRegistry(
        (
            _contract(
                name="read_account_state",
                risk=AgentToolRisk.READ_ONLY,
                permission=Permission.READ_CONTENT,
                input_model=AccountToolInput,
                output_model=ReadAccountStateOutput,
            ),
            _contract(
                name="run_content_analysis",
                risk=AgentToolRisk.DRAFT_WRITE,
                permission=Permission.WRITE_CONTENT,
                input_model=ContentToolInput,
                uses_external_api=True,
                retry_policy="manual",
            ),
            _contract(
                name="read_confirmed_facts",
                risk=AgentToolRisk.READ_ONLY,
                permission=Permission.READ_CONTENT,
                input_model=ReadConfirmedFactsInput,
            ),
            _contract(
                name="read_account_style",
                risk=AgentToolRisk.READ_ONLY,
                permission=Permission.READ_CONTENT,
                input_model=ReadAccountStyleInput,
            ),
            _contract(
                name="read_confirmed_viral_assets",
                risk=AgentToolRisk.READ_ONLY,
                permission=Permission.READ_CONTENT,
                input_model=ReadConfirmedViralAssetsInput,
            ),
            _contract(
                name="read_confirmed_hotspots",
                risk=AgentToolRisk.READ_ONLY,
                permission=Permission.READ_CONTENT,
                input_model=ReadConfirmedHotspotsInput,
            ),
            _contract(
                name="research_confirmed_hotspot",
                risk=AgentToolRisk.DRAFT_WRITE,
                permission=Permission.WRITE_CONTENT,
                input_model=ResearchConfirmedHotspotInput,
                uses_external_api=True,
                retry_policy="manual",
            ),
            _contract(
                name="generate_optimization_draft",
                risk=AgentToolRisk.DRAFT_WRITE,
                permission=Permission.WRITE_CONTENT,
                input_model=GenerateOptimizationDraftInput,
                uses_external_api=True,
                retry_policy="manual",
            ),
            _contract(
                name="scan_optimization_draft",
                risk=AgentToolRisk.DRAFT_WRITE,
                permission=Permission.WRITE_CONTENT,
                input_model=ContentToolInput,
                uses_external_api=True,
                retry_policy="manual",
            ),
            _contract(
                name="save_agent_summary",
                risk=AgentToolRisk.DRAFT_WRITE,
                permission=Permission.WRITE_CONTENT,
                input_model=ContentToolInput,
            ),
            _contract(
                name="create_agent_export",
                risk=AgentToolRisk.DRAFT_WRITE,
                permission=Permission.WRITE_CONTENT,
                input_model=ContentToolInput,
            ),
        ),
        catalog_version="operations-agent-tools-v1",
    )


DomainHandler = Callable[
    [Session, WorkspaceContext, ToolInvocation, BaseModel],
    BaseModel,
]


class DomainToolRunner:
    """Execute the closed, server-owned operations tool catalog."""

    def __init__(
        self,
        factory: sessionmaker[Session],
        *,
        registry: AgentToolRegistry | None = None,
    ) -> None:
        self._factory = factory
        self._registry = registry or build_domain_tool_registry()

    def invoke(self, invocation: ToolInvocation) -> ToolObservation:
        try:
            arguments = self._registry.validate_call(
                invocation.tool_name,
                invocation.arguments,
                version=invocation.tool_version,
            )
            with self._factory() as session:
                context = self._context(session, invocation)
                contract = self._registry.get(
                    invocation.tool_name,
                    version=invocation.tool_version,
                )
                require_permission(context.role, contract.permission)
                self._account(session, invocation, arguments)
                self._content(session, invocation, arguments)
                handler = getattr(self, f"_handle_{invocation.tool_name}")
                result = handler(session, context, invocation, arguments)
                validated = self._registry.validate_result(
                    invocation.tool_name,
                    result,
                    version=invocation.tool_version,
                )
                session.commit()
        except (
            AgentResourceScopeError,
            LookupError,
            PermissionDenied,
            PermissionError,
        ):
            return ToolObservation(
                status="denied",
                safe_summary="资源不属于当前工作区、平台或账号，工具未执行。",
                error_code="AGENT_RESOURCE_SCOPE_MISMATCH",
                next_valid_actions=("review_scope",),
            )
        except ModelProviderError as error:
            return ToolObservation(
                status=(
                    "unknown"
                    if error.code is ModelErrorCode.PROVIDER_OUTCOME_UNKNOWN
                    else "error"
                ),
                safe_summary=safe_model_error_message(error.code),
                error_code=error.code.value,
                next_valid_actions=("manual_review",),
            )
        except (ValueError, RuntimeError):
            return ToolObservation(
                status="error",
                safe_summary="当前条件不足，工具未生成或修改业务结果。",
                error_code="AGENT_TOOL_PREREQUISITE_MISSING",
                next_valid_actions=("review_inputs",),
            )
        payload = validated.model_dump()
        return ToolObservation(
            status="success",
            safe_summary=str(payload["safe_summary"]),
            artifact_refs=tuple(payload["artifact_refs"]),
            approval_exclusion_refs=tuple(payload["approval_exclusion_refs"]),
            evidence_refs=tuple(payload["evidence_refs"]),
        )

    @staticmethod
    def _context(
        session: Session,
        invocation: ToolInvocation,
    ) -> WorkspaceContext:
        member = session.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.id == invocation.actor_id,
                WorkspaceMember.workspace_id == invocation.workspace_id,
                WorkspaceMember.revoked_at.is_(None),
            )
        )
        if member is None:
            raise AgentResourceScopeError("workspace member not found")
        return WorkspaceContext(
            workspace_id=invocation.workspace_id,
            member_id=invocation.actor_id,
            role=cast(WorkspaceRole, member.role.value),
        )

    @staticmethod
    def _account(
        session: Session,
        invocation: ToolInvocation,
        arguments: BaseModel,
    ) -> PlatformAccount:
        account_id = getattr(arguments, "account_id", None)
        if account_id != invocation.account_id:
            raise AgentResourceScopeError("account scope mismatch")
        account = session.scalar(
            select(PlatformAccount).where(
                PlatformAccount.id == invocation.account_id,
                PlatformAccount.workspace_id == invocation.workspace_id,
                PlatformAccount.platform == Platform(invocation.platform),
            )
        )
        if account is None:
            raise AgentResourceScopeError("account not found")
        return account

    @staticmethod
    def _content(
        session: Session,
        invocation: ToolInvocation,
        arguments: BaseModel,
    ) -> Content | None:
        content_id = getattr(arguments, "content_id", None)
        if content_id is None:
            return None
        content = session.scalar(
            select(Content).where(
                Content.id == content_id,
                Content.workspace_id == invocation.workspace_id,
                Content.account_id == invocation.account_id,
                Content.platform == Platform(invocation.platform),
                Content.deleted_at.is_(None),
            )
        )
        if content is None:
            raise AgentResourceScopeError("content not found")
        return content

    @staticmethod
    def _handle_read_account_state(
        session: Session,
        context: WorkspaceContext,
        invocation: ToolInvocation,
        arguments: BaseModel,
    ) -> ReadAccountStateOutput:
        del context, arguments
        content_count = (
            session.scalar(
                select(func.count(Content.id)).where(
                    Content.workspace_id == invocation.workspace_id,
                    Content.account_id == invocation.account_id,
                    Content.deleted_at.is_(None),
                )
            )
            or 0
        )
        pending_count = (
            session.scalar(
                select(func.count(AnalysisRun.id)).where(
                    AnalysisRun.workspace_id == invocation.workspace_id,
                    AnalysisRun.account_id == invocation.account_id,
                    AnalysisRun.status.in_(
                        (AnalysisRunStatus.PENDING, AnalysisRunStatus.RUNNING)
                    ),
                )
            )
            or 0
        )
        return ReadAccountStateOutput(
            account_id=invocation.account_id,
            content_count=content_count,
            pending_analysis_count=pending_count,
            safe_summary=(
                f"账号状态读取完成：{content_count} 条内容，"
                f"{pending_count} 条分析处理中。"
            ),
        )

    @staticmethod
    def _handle_run_content_analysis(
        session: Session,
        context: WorkspaceContext,
        invocation: ToolInvocation,
        arguments: BaseModel,
    ) -> ResourceToolOutput:
        settings = get_settings()
        content_id = getattr(arguments, "content_id")
        run, _, created_by_agent = AnalysisService(session, context).request(
            content_id,
            trigger_kind="manual",
        )
        if run.status is AnalysisRunStatus.PENDING:
            if not created_by_agent:
                raise RuntimeError("existing pending analysis requires separate review")
            if not begin_analysis_attempt(session, run.id):
                raise RuntimeError("analysis is already owned by another worker")
            bundle = AnalysisEvidenceBundle.model_validate(run.evidence_bundle)
            adapter = (
                MockAnalysisAdapter()
                if settings.app_mock_mode
                else build_analysis_adapter_for_run(
                    session=session,
                    run=run,
                    platform=cast(
                        Literal["douyin", "xiaohongshu"],
                        invocation.platform,
                    ),
                    cipher=SecretCipher(
                        settings.model_secret_encryption_key.get_secret_value()
                    ),
                    mock_mode=False,
                )
            )
            session.commit()
            try:
                report = adapter.analyze(bundle)
                report.validate_references(bundle)
                run = persist_analysis_success(session, run.id, report)
            except ModelProviderError as error:
                persist_analysis_terminal_failure(
                    session,
                    run.id,
                    error_code=error.code.value,
                    error_message=safe_model_error_message(error.code),
                )
                session.commit()
                raise
            except Exception:
                persist_analysis_terminal_failure(
                    session,
                    run.id,
                    error_code="MODEL_ANALYSIS_FAILED",
                    error_message="模型分析失败，请人工检查后重试。",
                )
                session.commit()
                raise
        elif run.status is AnalysisRunStatus.RUNNING:
            raise RuntimeError("analysis is already owned by another worker")
        if run.status is not AnalysisRunStatus.SUCCEEDED:
            raise RuntimeError("analysis did not succeed")
        return ResourceToolOutput(
            resource_ids=(run.id,),
            artifact_refs=(f"analysis:{run.id}",),
            approval_exclusion_refs=(
                (f"analysis:{run.id}",) if created_by_agent else ()
            ),
            evidence_refs=(f"content:{content_id}",),
            safe_summary="内容分析已完成，并保留证据引用。",
        )

    @staticmethod
    def _handle_read_confirmed_facts(
        session: Session,
        context: WorkspaceContext,
        invocation: ToolInvocation,
        arguments: BaseModel,
    ) -> ResourceToolOutput:
        del invocation
        fact_context = FactSourceService(session, context).context()
        confirmed = fact_context["confirmed_items"]
        selected = set(getattr(arguments, "confirmed_fact_ids"))
        if selected:
            confirmed = [item for item in confirmed if item.id in selected]
            if {item.id for item in confirmed} != selected:
                raise AgentResourceScopeError("fact is not confirmed in workspace")
        ids = tuple(item.id for item in confirmed)
        return ResourceToolOutput(
            resource_ids=ids,
            evidence_refs=tuple(f"fact_item:{item_id}" for item_id in ids),
            safe_summary=(
                f"工作区有 {len(ids)} 条已确认事实；未明确选择前不会自动写入账号草稿。"
            ),
        )

    @staticmethod
    def _handle_read_account_style(
        session: Session,
        context: WorkspaceContext,
        invocation: ToolInvocation,
        arguments: BaseModel,
    ) -> ResourceToolOutput:
        try:
            profile, source = StyleProfileService(
                session,
                context,
            ).effective_profile(
                invocation.account_id,
                column_campaign_id=getattr(arguments, "column_campaign_id"),
            )
        except StyleProfileRequired:
            return ResourceToolOutput(
                safe_summary="当前账号没有已确认风格，后续将不沿用账号风格。",
            )
        return ResourceToolOutput(
            resource_ids=(profile.id,),
            evidence_refs=(f"style_profile:{profile.id}",),
            safe_summary=f"已读取账号生效风格（{source}）。",
        )

    @staticmethod
    def _handle_read_confirmed_viral_assets(
        session: Session,
        context: WorkspaceContext,
        invocation: ToolInvocation,
        arguments: BaseModel,
    ) -> ResourceToolOutput:
        items = ViralService(session, context).library_items(
            invocation.account_id,
            active_only=True,
        )
        selected = set(getattr(arguments, "viral_asset_ids"))
        if selected:
            items = [item for item in items if item.id in selected]
            if {item.id for item in items} != selected:
                raise AgentResourceScopeError("viral asset scope mismatch")
        items = items[:3]
        ids = tuple(item.id for item in items)
        return ResourceToolOutput(
            resource_ids=ids,
            evidence_refs=tuple(f"viral_asset:{item_id}" for item_id in ids),
            safe_summary=f"已读取 {len(ids)} 条可复用的已确认爆款结构。",
        )

    @staticmethod
    def _handle_read_confirmed_hotspots(
        session: Session,
        context: WorkspaceContext,
        invocation: ToolInvocation,
        arguments: BaseModel,
    ) -> ResourceToolOutput:
        del context
        query = select(HotspotSnapshot).where(
            HotspotSnapshot.workspace_id == invocation.workspace_id,
            HotspotSnapshot.target_platform == Platform(invocation.platform),
        )
        snapshot_id = getattr(arguments, "snapshot_id")
        if snapshot_id is not None:
            query = query.where(HotspotSnapshot.id == snapshot_id)
        snapshots = list(
            session.scalars(
                query.order_by(HotspotSnapshot.confirmed_at.desc()).limit(20)
            )
        )
        if snapshot_id is not None and not snapshots:
            raise AgentResourceScopeError("confirmed hotspot snapshot not found")
        ids = tuple(item.id for item in snapshots)
        entry_count = (
            session.scalar(
                select(func.count(HotspotEntry.id)).where(
                    HotspotEntry.snapshot_id.in_(ids),
                    HotspotEntry.selected.is_(True),
                )
            )
            if ids
            else 0
        )
        return ResourceToolOutput(
            resource_ids=ids,
            evidence_refs=tuple(f"hotspot_snapshot:{item_id}" for item_id in ids),
            safe_summary=f"已读取 {len(ids)} 份确认热点，共 {entry_count or 0} 条可用线索。",
        )

    @staticmethod
    def _handle_research_confirmed_hotspot(
        session: Session,
        context: WorkspaceContext,
        invocation: ToolInvocation,
        arguments: BaseModel,
    ) -> ResourceToolOutput:
        item = asyncio.run(
            HotspotResearchService(session, context).research(
                snapshot_id=getattr(arguments, "snapshot_id"),
                account_id=invocation.account_id,
                idempotency_key=f"agent-hotspot:{invocation.run_id}:{invocation.step_id}",
            )
        )
        if item.status.value != "succeeded":
            raise RuntimeError("hotspot research did not succeed")
        return ResourceToolOutput(
            resource_ids=(item.id,),
            artifact_refs=(f"hotspot_research:{item.id}",),
            approval_exclusion_refs=(f"hotspot_research:{item.id}",),
            evidence_refs=(
                f"hotspot_snapshot:{item.snapshot_id}",
                *(f"source_url:{source['url']}" for source in item.source_entries),
            ),
            safe_summary="已完成原生联网核实并生成带来源的热点创作候选，尚未发布。",
        )

    @staticmethod
    def _artifact_ids(
        session: Session,
        *,
        invocation: ToolInvocation,
        kind: AgentArtifactKind,
    ) -> tuple[UUID, ...]:
        return tuple(
            session.scalars(
                select(AgentArtifact.resource_id)
                .where(
                    AgentArtifact.workspace_id == invocation.workspace_id,
                    AgentArtifact.run_id == invocation.run_id,
                    AgentArtifact.kind == kind,
                )
                .order_by(AgentArtifact.created_at, AgentArtifact.id)
            )
        )

    @classmethod
    def _handle_generate_optimization_draft(
        cls,
        session: Session,
        context: WorkspaceContext,
        invocation: ToolInvocation,
        arguments: BaseModel,
    ) -> ResourceToolOutput:
        settings = get_settings()
        content = cls._content(session, invocation, arguments)
        assert content is not None
        if settings.app_mock_mode:
            configs = list(
                session.scalars(
                    select(ModelConfig)
                    .where(
                        ModelConfig.workspace_id == invocation.workspace_id,
                        ModelConfig.provider == "mock",
                        ModelConfig.status != ModelConfigStatus.INCOMPATIBLE,
                    )
                    .order_by(ModelConfig.id)
                )
            )
            model = next(
                (
                    config
                    for config in configs
                    if Capability.TEXT.value in config.capabilities
                ),
                None,
            )
        else:
            model = ModelConfigService(
                session,
                context,
                cipher=SecretCipher(
                    settings.model_secret_encryption_key.get_secret_value()
                ),
            ).resolve({Capability.TEXT}, provider="qianwen")
        if model is None:
            raise RuntimeError("text model configuration required")
        fact_ids = tuple(getattr(arguments, "confirmed_fact_ids"))
        requested_style_id = getattr(arguments, "style_profile_id")
        style_id = requested_style_id
        if style_id is None:
            try:
                profile, _ = StyleProfileService(
                    session,
                    context,
                ).effective_profile(
                    invocation.account_id,
                    column_campaign_id=content.column_campaign_id,
                )
                style_id = profile.id
            except StyleProfileRequired:
                style_id = None
        viral_ids = tuple(getattr(arguments, "viral_asset_ids"))
        if not viral_ids:
            viral_ids = tuple(
                item.id
                for item in ViralService(session, context).library_items(
                    invocation.account_id,
                    active_only=True,
                )[:3]
            )
        generation = GenerationContextBuilder(session, context).create_run(
            GenerationInputs(
                account_id=invocation.account_id,
                platform=Platform(invocation.platform),
                column_campaign_id=content.column_campaign_id,
                target=content.title,
                confirmed_fact_item_ids=fact_ids,
                style_profile_id=style_id,
                style_switches=StyleInheritanceSelection(
                    title=bool(style_id) and getattr(arguments, "preserve_title_style"),
                    copy=bool(style_id) and getattr(arguments, "preserve_copy_style"),
                    cover=bool(style_id) and getattr(arguments, "preserve_cover_style"),
                ),
                viral_library_item_ids=viral_ids,
                user_prompt=getattr(arguments, "user_instruction"),
                risk_rule_version="operations-agent-risk-v1",
                model_config_id=model.id,
            )
        )
        run, _, created_by_agent = create_text_generation_with_provenance(
            session,
            generation.context,
            requested_by=context.member_id,
            use_cache=True,
        )
        if run.status is TextGenerationRunStatus.SUCCEEDED:
            return ResourceToolOutput(
                resource_ids=(run.id,),
                artifact_refs=(
                    f"text_draft:{run.id}",
                    f"cover_recommendation:{run.id}",
                ),
                evidence_refs=(f"content:{content.id}",),
                safe_summary=("已复用同一生成上下文的成功草稿，尚未发布。"),
            )
        if not created_by_agent:
            raise RuntimeError(
                "existing pending text generation requires separate review"
            )
        if not begin_text_generation_attempt(session, run.id):
            raise RuntimeError("text generation is already owned by another worker")
        adapter = build_text_adapter_for_run(
            session=session,
            run=run,
            cipher=SecretCipher(
                settings.model_secret_encryption_key.get_secret_value()
            ),
            mock_mode=settings.app_mock_mode,
        )
        generation_context = generation.context
        session.commit()
        try:
            generated = asyncio.run(generate_text(generation_context, adapter))
            run = persist_text_generation_success(
                session,
                run.id,
                generated,
                provider_mode=("mock" if settings.app_mock_mode else "real"),
            )
        except ModelProviderError as error:
            persist_text_generation_failure(
                session,
                run.id,
                error_code=error.code.value,
                status_detail=safe_model_error_message(error.code),
            )
            session.commit()
            raise
        except Exception:
            persist_text_generation_failure(
                session,
                run.id,
                error_code="MODEL_GENERATION_FAILED",
                status_detail="文本模型生成失败，请人工检查后重试。",
            )
            session.commit()
            raise
        if run.status is not TextGenerationRunStatus.SUCCEEDED:
            raise RuntimeError("text generation did not succeed")
        return ResourceToolOutput(
            resource_ids=(run.id,),
            artifact_refs=(
                f"text_draft:{run.id}",
                f"cover_recommendation:{run.id}",
            ),
            approval_exclusion_refs=(f"text_draft:{run.id}",),
            evidence_refs=(
                f"content:{content.id}",
                *(f"fact_item:{item_id}" for item_id in fact_ids),
            ),
            safe_summary="优化标题、文案和程序化封面建议已生成，尚未发布。",
        )

    @classmethod
    def _handle_scan_optimization_draft(
        cls,
        session: Session,
        context: WorkspaceContext,
        invocation: ToolInvocation,
        arguments: BaseModel,
    ) -> ResourceToolOutput:
        content = cls._content(session, invocation, arguments)
        assert content is not None
        draft_ids = cls._artifact_ids(
            session,
            invocation=invocation,
            kind=AgentArtifactKind.TEXT_DRAFT,
        )
        if not draft_ids:
            raise RuntimeError("generated draft required")
        draft = session.scalar(
            select(TextGenerationRun).where(
                TextGenerationRun.id == draft_ids[-1],
                TextGenerationRun.workspace_id == invocation.workspace_id,
                TextGenerationRun.account_id == invocation.account_id,
                TextGenerationRun.status == TextGenerationRunStatus.SUCCEEDED,
            )
        )
        if draft is None or draft.final_title is None or draft.final_copy is None:
            raise RuntimeError("generated draft unavailable")
        requested_at = datetime.now(UTC)
        active_filter = None
        if not get_settings().app_mock_mode:
            try:
                active_filter = resolve_active_retrieval_filter(
                    session,
                    workspace_id=invocation.workspace_id,
                    platform=Platform(invocation.platform),
                    as_of=requested_at,
                )
            except ActiveRiskIndexUnavailable:
                active_filter = None
        versions = RiskScanVersions(
            rule_version="operations-agent-risk-v1",
            evidence_version=(
                active_filter.index_generation
                if active_filter is not None
                and active_filter.index_generation is not None
                else "no-active-risk-evidence"
            ),
            embedding_model_id=(
                active_filter.embedding_model_id
                if active_filter is not None
                else "mock-risk-embedding"
            ),
            embedding_version=(
                active_filter.embedding_version
                if active_filter is not None
                else "mock-risk-embedding-v1"
            ),
            embedding_dimension=(
                active_filter.embedding_dimension if active_filter is not None else 3
            ),
            rag_model_version="mock-risk-rag-v1",
            scanner_version="operations-agent-scanner-v1",
        )
        scan_input = RiskScanInput(
            workspace_id=invocation.workspace_id,
            account_id=invocation.account_id,
            content_id=content.id,
            platform=Platform(invocation.platform),
            node=RiskScanNode.AFTER_GENERATION,
            title=draft.final_title,
            body=draft.final_copy,
            ocr=OcrResult(status=OcrStatus.EMPTY, regions=()),
            idempotency_key=f"agent-risk:{invocation.run_id}:{invocation.step_id}",
            versions=versions,
            requested_at=requested_at,
        )
        pipeline = build_default_pipeline(
            session,
            scan_input,
            context=context,
        )
        session.commit()
        scan = RiskScanService(session, context=context).execute(
            scan_input,
            pipeline=pipeline,
        )
        return ResourceToolOutput(
            resource_ids=(scan.id,),
            artifact_refs=(f"risk_scan:{scan.id}",),
            approval_exclusion_refs=(f"risk_scan:{scan.id}",),
            evidence_refs=(f"text_draft:{draft.id}",),
            safe_summary="优化草稿已完成风控扫描，仍需人工复核后使用。",
        )

    @staticmethod
    def _handle_save_agent_summary(
        session: Session,
        context: WorkspaceContext,
        invocation: ToolInvocation,
        arguments: BaseModel,
    ) -> ResourceToolOutput:
        del arguments
        event = session.scalar(
            select(AgentEvent).where(
                AgentEvent.workspace_id == invocation.workspace_id,
                AgentEvent.idempotency_key == f"agent-summary:{invocation.run_id}",
            )
        )
        if event is None:
            event = AgentEvent(
                workspace_id=invocation.workspace_id,
                event_type="execution_summary_saved",
                idempotency_key=f"agent-summary:{invocation.run_id}",
                safe_payload={
                    "publication_performed": False,
                    "scope": "analysis_draft_review_export",
                },
                run_id=invocation.run_id,
                step_id=invocation.step_id,
                actor_id=context.member_id,
            )
            session.add(event)
            session.flush()
        return ResourceToolOutput(
            resource_ids=(event.id,),
            artifact_refs=(f"execution_summary:{event.id}",),
            safe_summary="本次执行摘要已保存；系统没有执行发布。",
        )

    @staticmethod
    def _handle_create_agent_export(
        session: Session,
        context: WorkspaceContext,
        invocation: ToolInvocation,
        arguments: BaseModel,
    ) -> ResourceToolOutput:
        content_id = getattr(arguments, "content_id")
        task, _ = create_export_task(
            session,
            context,
            kind=ExportKind.MARKDOWN,
            content_id=content_id,
            idempotency_key=f"agent-export:{invocation.run_id}",
        )
        return ResourceToolOutput(
            resource_ids=(task.id,),
            artifact_refs=(f"export:{task.id}",),
            approval_exclusion_refs=(f"export:{task.id}",),
            evidence_refs=(f"content:{content_id}",),
            safe_summary="Markdown 执行包已创建，可在导出任务中查看状态。",
        )
