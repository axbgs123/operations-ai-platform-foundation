from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from typing import Protocol, cast
from uuid import UUID

from pydantic import JsonValue, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import utc_now
from app.core.security import WorkspaceContext, WorkspaceRole
from app.modules.content.account_models import (
    BenchmarkProfile,
    ColumnCampaign,
    ObjectiveProfile,
    PlatformAccount,
)
from app.modules.models.models import ModelConfig
from app.modules.operations_agent.briefing import BriefingService
from app.modules.operations_agent.models import (
    AgentArtifact,
    AgentArtifactKind,
    AgentBriefing,
    AgentEvent,
    AgentPlan,
    AgentPlanStatus,
)
from app.modules.operations_agent.schemas import (
    AgentPlanApprovalSnapshot,
    AgentPlanCreate,
    AgentPlanDocument,
    AgentPlanRead,
    AgentPlanStep,
    AllowedToolSummary,
    BriefingCandidateRead,
    DailyBriefingRead,
    PlannerRequest,
    StoredAgentPlanDocument,
)
from app.modules.operations_agent.tools import (
    AgentToolInputError,
    AgentToolRegistry,
)
from app.modules.risk_rag.models import RiskScan
from app.modules.workspace.models import WorkspaceMember
from app.modules.workspace.permissions import Permission, require_permission


class InvalidAgentPlan(ValueError):
    pass


class AgentApprovalStale(RuntimeError):
    pass


_PLANNING_PREREQUISITES: Mapping[str, tuple[str, ...]] = {
    "read_account_state": (),
    "run_content_analysis": ("read_account_state",),
    "read_confirmed_facts": ("read_account_state",),
    "read_account_style": ("read_account_state",),
    "read_confirmed_viral_assets": ("read_account_state",),
    "generate_optimization_draft": (
        "run_content_analysis",
        "read_confirmed_facts",
        "read_account_style",
        "read_confirmed_viral_assets",
    ),
    "scan_optimization_draft": ("generate_optimization_draft",),
    "save_agent_summary": ("scan_optimization_draft",),
    "create_agent_export": ("save_agent_summary",),
}


def build_planning_registry() -> AgentToolRegistry:
    from app.modules.operations_agent.domain_tools import (
        build_domain_tool_registry,
    )

    return build_domain_tool_registry()


class AgentPlanner(Protocol):
    def create_plan(self, request: PlannerRequest) -> AgentPlanDocument: ...


class DeterministicPlanner:
    def __init__(self, *, tool_catalog_version: str) -> None:
        self._tool_catalog_version = tool_catalog_version

    def create_plan(self, request: PlannerRequest) -> AgentPlanDocument:
        content_id = self._content_id(request.evidence_refs)
        tool_by_name = {tool.name: tool for tool in request.allowed_tools}
        step_specs: list[tuple[str, dict[str, JsonValue], str]] = [
            (
                "read_account_state",
                {"account_id": str(request.account_id)},
                "读取账号安全状态，确认本次执行范围。",
            )
        ]
        if content_id is not None:
            common: dict[str, JsonValue] = {
                "account_id": str(request.account_id),
                "content_id": str(content_id),
            }
            step_specs.extend(
                [
                    ("run_content_analysis", common, "基于已确认数据完成内容分析。"),
                    (
                        "read_confirmed_facts",
                        {"account_id": str(request.account_id)},
                        "读取工作区内可用于生成的已确认事实。",
                    ),
                    (
                        "read_account_style",
                        {"account_id": str(request.account_id)},
                        "读取该账号当前生效的已确认风格。",
                    ),
                    (
                        "read_confirmed_viral_assets",
                        {"account_id": str(request.account_id)},
                        "读取该账号最多三条可复用爆款结构。",
                    ),
                    (
                        "generate_optimization_draft",
                        common,
                        "生成标题、文案及程序化封面建议，不执行发布。",
                    ),
                    (
                        "scan_optimization_draft",
                        common,
                        "对优化草稿执行发布前风控扫描。",
                    ),
                    (
                        "save_agent_summary",
                        common,
                        "保存不含敏感正文的执行摘要。",
                    ),
                    (
                        "create_agent_export",
                        common,
                        "创建 Markdown 执行包，不返回长期下载地址。",
                    ),
                ]
            )
        return AgentPlanDocument(
            goal=request.objective,
            platform=request.platform,
            account_id=request.account_id,
            candidate_id=request.candidate_id,
            input_fingerprint=request.briefing_input_fingerprint,
            tool_catalog_version=self._tool_catalog_version,
            steps=tuple(
                AgentPlanStep(
                    step_index=index,
                    tool_name=name,
                    tool_version=tool_by_name[name].version,
                    arguments=arguments,
                    rationale=rationale,
                )
                for index, (name, arguments, rationale) in enumerate(step_specs)
            ),
        )

    @staticmethod
    def _content_id(evidence_refs: tuple[str, ...]) -> UUID | None:
        for reference in evidence_refs:
            kind, separator, raw_id = reference.partition(":")
            if kind != "content" or not separator:
                continue
            try:
                return UUID(raw_id)
            except ValueError:
                continue
        return None


class PlanValidator:
    def __init__(self, registry: AgentToolRegistry) -> None:
        self._registry = registry

    def validate(
        self,
        *,
        model_output: object,
        request: PlannerRequest,
    ) -> AgentPlanDocument:
        payload = self._parse_one_object(model_output)
        try:
            plan = AgentPlanDocument.model_validate(payload)
        except ValidationError as error:
            raise InvalidAgentPlan("plan output does not match schema") from error
        if (
            plan.goal != request.objective
            or plan.platform is not request.platform
            or plan.account_id != request.account_id
            or plan.candidate_id != request.candidate_id
            or plan.input_fingerprint
            != request.briefing_input_fingerprint
            or plan.tool_catalog_version != self._registry.catalog_version
        ):
            raise InvalidAgentPlan("plan changed server-controlled scope")
        allowed = {
            (tool.name, tool.version): tool for tool in request.allowed_tools
        }
        previous_names: set[str] = set()
        for step in plan.steps:
            summary = allowed.get((step.tool_name, step.tool_version))
            if summary is None:
                raise InvalidAgentPlan(
                    f"unknown agent tool {step.tool_name!r}"
                )
            try:
                validated = self._registry.validate_call(
                    step.tool_name,
                    step.arguments,
                    version=step.tool_version,
                )
            except AgentToolInputError as error:
                raise InvalidAgentPlan(str(error)) from error
            arguments = validated.model_dump(mode="json")
            raw_account_id = arguments.get("account_id")
            if (
                raw_account_id is not None
                and UUID(str(raw_account_id)) != request.account_id
            ):
                raise InvalidAgentPlan("plan changed account scope")
            prerequisites = set(summary.prerequisites)
            if not prerequisites <= previous_names:
                raise InvalidAgentPlan("plan is missing tool prerequisites")
            previous_names.add(step.tool_name)
        return plan

    @staticmethod
    def _parse_one_object(model_output: object) -> object:
        if not isinstance(model_output, str):
            return model_output
        stripped = model_output.strip()
        if stripped.startswith("```"):
            raise InvalidAgentPlan("Markdown plan output is not allowed")

        def reject_duplicate_keys(
            pairs: list[tuple[str, object]],
        ) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise InvalidAgentPlan(
                        f"duplicate JSON key {key!r} is not allowed"
                    )
                result[key] = value
            return result

        decoder = json.JSONDecoder(object_pairs_hook=reject_duplicate_keys)
        try:
            payload, index = decoder.raw_decode(stripped)
        except json.JSONDecodeError as error:
            raise InvalidAgentPlan("plan output is not valid JSON") from error
        if stripped[index:].strip():
            raise InvalidAgentPlan("plan output contains extra prose")
        if not isinstance(payload, dict):
            raise InvalidAgentPlan("plan output must be one JSON object")
        return payload


class PlanService:
    def __init__(
        self,
        session: Session,
        context: WorkspaceContext,
        *,
        registry: AgentToolRegistry | None = None,
        planner: AgentPlanner | None = None,
    ) -> None:
        if context.member_id is None or context.role == "demo":
            raise PermissionError("private operations agent unavailable")
        self._session = session
        self._context = context
        self._registry = registry or build_planning_registry()
        self._planner = planner or DeterministicPlanner(
            tool_catalog_version=self._registry.catalog_version
        )
        self._validator = PlanValidator(self._registry)

    def create(
        self,
        data: AgentPlanCreate,
        *,
        idempotency_key: str,
    ) -> AgentPlanRead:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise ValueError("invalid idempotency key")
        existing = self._session.scalar(
            select(AgentPlan).where(
                AgentPlan.workspace_id == self._context.workspace_id,
                AgentPlan.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            stored = StoredAgentPlanDocument.model_validate(existing.document)
            if (
                existing.briefing_id != data.briefing_id
                or existing.account_id != data.account_id
                or existing.platform is not data.platform
                or stored.plan.goal != data.objective
            ):
                raise ValueError("idempotency key conflict")
            return self._read(existing)

        briefing = self._briefing(data.briefing_id)
        latest = BriefingService(
            self._session,
            self._context,
        ).generate()
        if latest.id != briefing.id:
            raise AgentApprovalStale("briefing is no longer current")
        primary = self._primary(briefing)
        if (
            primary.account_id != data.account_id
            or primary.platform is not data.platform
        ):
            raise InvalidAgentPlan(
                "plan scope must match the primary briefing candidate"
            )
        request = PlannerRequest(
            objective=data.objective,
            briefing_id=briefing.id,
            platform=data.platform,
            account_id=data.account_id,
            candidate_id=primary.candidate_id,
            briefing_input_fingerprint=briefing.input_fingerprint,
            allowed_tools=self._allowed_tools(),
            evidence_refs=primary.evidence_refs,
        )
        generated = self._planner.create_plan(request)
        document = self._validator.validate(
            model_output=generated.model_dump(mode="json"),
            request=request,
        )
        stored_document = StoredAgentPlanDocument(
            plan=document,
            approval_snapshot=self._approval_snapshot(
                briefing_input_fingerprint=briefing.input_fingerprint,
                account_id=data.account_id,
            ),
        )
        plan_fingerprint = _fingerprint(
            stored_document.model_dump(mode="json")
        )
        plan = AgentPlan(
            workspace_id=self._context.workspace_id,
            briefing_id=briefing.id,
            account_id=data.account_id,
            platform=data.platform,
            idempotency_key=idempotency_key,
            input_fingerprint=briefing.input_fingerprint,
            tool_catalog_version=self._registry.catalog_version,
            document=stored_document.model_dump(mode="json"),
            plan_fingerprint=plan_fingerprint,
            status=AgentPlanStatus.DRAFT,
            created_by=self._context.member_id,
        )
        self._session.add(plan)
        self._session.flush()
        return self._read(plan)

    def get(self, plan_id: UUID) -> AgentPlanRead:
        require_permission(self._context.role, Permission.READ_CONTENT)
        return self._read(self._plan(plan_id))

    def approve(self, plan_id: UUID) -> AgentPlanRead:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        plan = self._plan(plan_id)
        if plan.status is AgentPlanStatus.APPROVED:
            return self._read(plan)
        if plan.status is not AgentPlanStatus.DRAFT:
            raise ValueError("plan is terminal and cannot be approved")
        self._ensure_current(plan)
        plan.status = AgentPlanStatus.APPROVED
        plan.approved_by = self._context.member_id
        plan.approved_at = utc_now()
        self._append_event(
            plan,
            event_type="plan_approved",
            idempotency_key=f"plan-approved:{plan.id}",
        )
        self._session.flush()
        return self._read(plan)

    def reject(self, plan_id: UUID) -> AgentPlanRead:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        plan = self._plan(plan_id)
        if plan.status is AgentPlanStatus.REJECTED:
            return self._read(plan)
        if plan.status is not AgentPlanStatus.DRAFT:
            raise ValueError("plan is terminal and cannot be rejected")
        plan.status = AgentPlanStatus.REJECTED
        self._append_event(
            plan,
            event_type="plan_rejected",
            idempotency_key=f"plan-rejected:{plan.id}",
        )
        self._session.flush()
        return self._read(plan)

    def assert_approval_current(self, plan_id: UUID) -> AgentPlanRead:
        require_permission(self._context.role, Permission.READ_CONTENT)
        plan = self._plan(plan_id)
        if plan.status is not AgentPlanStatus.APPROVED:
            raise ValueError("plan is not approved")
        self._ensure_current(plan)
        return self._read(plan)

    def assert_execution_current(
        self,
        plan_id: UUID,
        *,
        run_id: UUID,
        additional_artifact_refs: tuple[str, ...] = (),
    ) -> AgentPlanRead:
        require_permission(self._context.role, Permission.READ_CONTENT)
        plan = self._plan(plan_id)
        if plan.status is not AgentPlanStatus.APPROVED:
            raise ValueError("plan is not approved")
        artifacts = list(
            self._session.scalars(
                select(AgentArtifact).where(
                    AgentArtifact.workspace_id
                    == self._context.workspace_id,
                    AgentArtifact.run_id == run_id,
                )
            )
        )
        additional = self._artifact_ref_ids(additional_artifact_refs)
        analysis_ids = frozenset(
            artifact.resource_id
            for artifact in artifacts
            if artifact.kind is AgentArtifactKind.ANALYSIS
            and artifact.safe_metadata.get("approval_exclusion") is True
        ) | additional[AgentArtifactKind.ANALYSIS]
        scan_ids = frozenset(
            artifact.resource_id
            for artifact in artifacts
            if artifact.kind is AgentArtifactKind.RISK_SCAN
            and artifact.safe_metadata.get("approval_exclusion") is True
        ) | additional[AgentArtifactKind.RISK_SCAN]
        generation_ids = frozenset(
            artifact.resource_id
            for artifact in artifacts
            if artifact.kind is AgentArtifactKind.TEXT_DRAFT
            and artifact.safe_metadata.get("approval_exclusion") is True
        ) | additional[AgentArtifactKind.TEXT_DRAFT]
        export_ids = frozenset(
            artifact.resource_id
            for artifact in artifacts
            if artifact.kind is AgentArtifactKind.EXPORT
            and artifact.safe_metadata.get("approval_exclusion") is True
        ) | additional[AgentArtifactKind.EXPORT]
        stored = StoredAgentPlanDocument.model_validate(plan.document)
        creator_context = self._creator_context(plan)
        current_briefing_fingerprint = BriefingService(
            self._session,
            creator_context,
        ).current_input_fingerprint(
            excluded_analysis_ids=analysis_ids,
            excluded_generation_ids=generation_ids,
            excluded_scan_ids=scan_ids,
            excluded_export_ids=export_ids,
        )
        current = StoredAgentPlanDocument(
            plan=stored.plan,
            approval_snapshot=self._approval_snapshot(
                briefing_input_fingerprint=current_briefing_fingerprint,
                account_id=plan.account_id,
                excluded_scan_ids=scan_ids,
            ),
        )
        if (
            _fingerprint(current.model_dump(mode="json"))
            != plan.plan_fingerprint
            or plan.tool_catalog_version != self._registry.catalog_version
        ):
            raise AgentApprovalStale(
                "plan approval is stale: "
                f"briefing={current.approval_snapshot.briefing_input_fingerprint == stored.approval_snapshot.briefing_input_fingerprint},"
                f"account={current.approval_snapshot.account_configuration_version == stored.approval_snapshot.account_configuration_version},"
                f"model={current.approval_snapshot.model_configuration_version == stored.approval_snapshot.model_configuration_version},"
                f"risk={current.approval_snapshot.risk_rule_version == stored.approval_snapshot.risk_rule_version}"
            )
        return self._read(plan)

    @staticmethod
    def _artifact_ref_ids(
        references: tuple[str, ...],
    ) -> dict[AgentArtifactKind, frozenset[UUID]]:
        collected: dict[AgentArtifactKind, set[UUID]] = {
            AgentArtifactKind.ANALYSIS: set(),
            AgentArtifactKind.TEXT_DRAFT: set(),
            AgentArtifactKind.RISK_SCAN: set(),
            AgentArtifactKind.EXPORT: set(),
        }
        for reference in references:
            raw_kind, separator, raw_id = reference.partition(":")
            if not separator:
                continue
            try:
                kind = AgentArtifactKind(raw_kind)
                resource_id = UUID(raw_id)
            except ValueError:
                continue
            if kind in collected:
                collected[kind].add(resource_id)
        return {
            kind: frozenset(resource_ids)
            for kind, resource_ids in collected.items()
        }

    def _ensure_current(self, plan: AgentPlan) -> None:
        stored = StoredAgentPlanDocument.model_validate(plan.document)
        latest_briefing = self._latest_creator_briefing(plan)
        current = StoredAgentPlanDocument(
            plan=stored.plan,
            approval_snapshot=self._approval_snapshot(
                briefing_input_fingerprint=(
                    latest_briefing.input_fingerprint
                ),
                account_id=plan.account_id,
            ),
        )
        current_fingerprint = _fingerprint(
            current.model_dump(mode="json")
        )
        if (
            current_fingerprint != plan.plan_fingerprint
            or plan.tool_catalog_version != self._registry.catalog_version
        ):
            raise AgentApprovalStale("plan approval is stale")

    def _latest_creator_briefing(
        self,
        plan: AgentPlan,
    ) -> AgentBriefing | DailyBriefingRead:
        creator_context = self._creator_context(plan)
        briefing = BriefingService(
            self._session,
            creator_context,
        ).generate()
        source = self._briefing(plan.briefing_id)
        if briefing.input_fingerprint != source.input_fingerprint:
            return briefing
        return source

    def _creator_context(self, plan: AgentPlan) -> WorkspaceContext:
        if plan.created_by is None:
            raise AgentApprovalStale("plan creator is no longer available")
        creator = self._session.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.id == plan.created_by,
                WorkspaceMember.workspace_id == self._context.workspace_id,
                WorkspaceMember.revoked_at.is_(None),
            )
        )
        if creator is None:
            raise AgentApprovalStale("plan creator is no longer available")
        return WorkspaceContext(
            workspace_id=self._context.workspace_id,
            member_id=creator.id,
            role=cast(WorkspaceRole, creator.role.value),
        )

    def _approval_snapshot(
        self,
        *,
        briefing_input_fingerprint: str,
        account_id: UUID,
        excluded_scan_ids: frozenset[UUID] = frozenset(),
    ) -> AgentPlanApprovalSnapshot:
        return AgentPlanApprovalSnapshot(
            briefing_input_fingerprint=briefing_input_fingerprint,
            account_configuration_version=self._account_version(account_id),
            model_configuration_version=self._model_version(),
            risk_rule_version=self._risk_version(
                account_id,
                excluded_scan_ids=excluded_scan_ids,
            ),
        )

    def _account_version(self, account_id: UUID) -> str:
        account = self._session.scalar(
            select(PlatformAccount).where(
                PlatformAccount.id == account_id,
                PlatformAccount.workspace_id == self._context.workspace_id,
            )
        )
        if account is None:
            raise LookupError("account not found")
        objectives = list(
            self._session.scalars(
                select(ObjectiveProfile)
                .where(
                    ObjectiveProfile.workspace_id
                    == self._context.workspace_id,
                    ObjectiveProfile.account_id == account_id,
                )
                .order_by(ObjectiveProfile.id)
            )
        )
        benchmarks = list(
            self._session.scalars(
                select(BenchmarkProfile)
                .where(
                    BenchmarkProfile.workspace_id
                    == self._context.workspace_id,
                    BenchmarkProfile.account_id == account_id,
                )
                .order_by(BenchmarkProfile.id)
            )
        )
        columns = list(
            self._session.scalars(
                select(ColumnCampaign)
                .where(
                    ColumnCampaign.workspace_id
                    == self._context.workspace_id,
                    ColumnCampaign.account_id == account_id,
                )
                .order_by(ColumnCampaign.id)
            )
        )
        return _fingerprint(
            {
                "account": {
                    "id": str(account.id),
                    "platform": account.platform.value,
                    "name": account.name,
                    "updated_at": account.updated_at.isoformat(),
                },
                "objectives": [
                    {
                        "id": str(item.id),
                        "version": item.version,
                        "updated_at": item.updated_at.isoformat(),
                    }
                    for item in objectives
                ],
                "benchmarks": [
                    {
                        "id": str(item.id),
                        "version": item.version,
                        "updated_at": item.updated_at.isoformat(),
                    }
                    for item in benchmarks
                ],
                "columns": [
                    {
                        "id": str(item.id),
                        "updated_at": item.updated_at.isoformat(),
                    }
                    for item in columns
                ],
            }
        )

    def _model_version(self) -> str:
        configs = list(
            self._session.scalars(
                select(ModelConfig)
                .where(
                    ModelConfig.workspace_id == self._context.workspace_id
                )
                .order_by(ModelConfig.id)
            )
        )
        return _fingerprint(
            [
                {
                    "id": str(item.id),
                    "provider": item.provider,
                    "model_id": item.model_id,
                    "capabilities": sorted(item.capabilities),
                    "status": item.status.value,
                    "configuration_revision": item.configuration_revision,
                    "updated_at": item.updated_at.isoformat(),
                }
                for item in configs
            ]
        )

    def _risk_version(
        self,
        account_id: UUID,
        *,
        excluded_scan_ids: frozenset[UUID] = frozenset(),
    ) -> str:
        query = select(RiskScan).where(
            RiskScan.workspace_id == self._context.workspace_id,
            RiskScan.account_id == account_id,
        )
        if excluded_scan_ids:
            query = query.where(RiskScan.id.not_in(excluded_scan_ids))
        scans = list(
            self._session.scalars(
                query.order_by(RiskScan.id)
            )
        )
        return _fingerprint(
            [
                {
                    "id": str(item.id),
                    "rule_version": item.rule_version,
                    "evidence_version": item.evidence_version,
                    "scanner_version": item.scanner_version,
                    "updated_at": item.updated_at.isoformat(),
                }
                for item in scans
            ]
        )

    def _allowed_tools(self) -> tuple[AllowedToolSummary, ...]:
        return tuple(
            AllowedToolSummary(
                name=contract.name,
                version=contract.version,
                risk=contract.risk,
                prerequisites=_PLANNING_PREREQUISITES[contract.name],
            )
            for contract in self._registry.contracts()
        )

    def _briefing(self, briefing_id: UUID) -> AgentBriefing:
        briefing = self._session.scalar(
            select(AgentBriefing).where(
                AgentBriefing.id == briefing_id,
                AgentBriefing.workspace_id == self._context.workspace_id,
            )
        )
        if briefing is None:
            raise LookupError("briefing not found")
        return briefing

    @staticmethod
    def _primary(briefing: AgentBriefing) -> BriefingCandidateRead:
        if briefing.priority_candidate is None:
            raise InvalidAgentPlan("briefing has no actionable candidate")
        return BriefingCandidateRead.model_validate(
            briefing.priority_candidate
        )

    def _plan(self, plan_id: UUID) -> AgentPlan:
        plan = self._session.scalar(
            select(AgentPlan).where(
                AgentPlan.id == plan_id,
                AgentPlan.workspace_id == self._context.workspace_id,
            )
        )
        if plan is None:
            raise LookupError("plan not found")
        return plan

    def _append_event(
        self,
        plan: AgentPlan,
        *,
        event_type: str,
        idempotency_key: str,
    ) -> None:
        existing = self._session.scalar(
            select(AgentEvent).where(
                AgentEvent.workspace_id == self._context.workspace_id,
                AgentEvent.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return
        self._session.add(
            AgentEvent(
                workspace_id=self._context.workspace_id,
                event_type=event_type,
                idempotency_key=idempotency_key,
                safe_payload={"plan_id": str(plan.id)},
                actor_id=self._context.member_id,
            )
        )

    @staticmethod
    def _read(plan: AgentPlan) -> AgentPlanRead:
        stored = StoredAgentPlanDocument.model_validate(plan.document)
        return AgentPlanRead(
            id=plan.id,
            workspace_id=plan.workspace_id,
            briefing_id=plan.briefing_id,
            account_id=plan.account_id,
            platform=plan.platform,
            status=plan.status,
            document=stored.plan,
            approval_snapshot=stored.approval_snapshot,
            plan_fingerprint=plan.plan_fingerprint,
            tool_catalog_version=plan.tool_catalog_version,
            approved_by=plan.approved_by,
            approved_at=plan.approved_at,
            created_at=plan.created_at,
        )


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
