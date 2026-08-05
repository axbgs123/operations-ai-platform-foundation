from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from typing import Protocol, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError
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
    AgentBriefing,
    AgentEvent,
    AgentPlan,
    AgentPlanStatus,
    AgentToolRisk,
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
    AgentToolContract,
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


class ReadAccountStateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: UUID


class ReadAccountStateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: UUID
    safe_summary: str


_PLANNING_PREREQUISITES: Mapping[str, tuple[str, ...]] = {
    "read_account_state": (),
}


def build_planning_registry() -> AgentToolRegistry:
    return AgentToolRegistry(
        [
            AgentToolContract(
                name="read_account_state",
                version="1.0.0",
                risk=AgentToolRisk.READ_ONLY,
                permission=Permission.READ_CONTENT,
                uses_external_api=False,
                retry_policy="safe",
                input_model=ReadAccountStateInput,
                output_model=ReadAccountStateOutput,
            )
        ],
        catalog_version="agent-tools-v1",
    )


class AgentPlanner(Protocol):
    def create_plan(self, request: PlannerRequest) -> AgentPlanDocument: ...


class DeterministicPlanner:
    def __init__(self, *, tool_catalog_version: str) -> None:
        self._tool_catalog_version = tool_catalog_version

    def create_plan(self, request: PlannerRequest) -> AgentPlanDocument:
        tool = request.allowed_tools[0]
        return AgentPlanDocument(
            goal=request.objective,
            platform=request.platform,
            account_id=request.account_id,
            candidate_id=request.candidate_id,
            input_fingerprint=request.briefing_input_fingerprint,
            tool_catalog_version=self._tool_catalog_version,
            steps=(
                AgentPlanStep(
                    step_index=0,
                    tool_name=tool.name,
                    tool_version=tool.version,
                    arguments={"account_id": str(request.account_id)},
                    rationale="读取账号的安全状态摘要，确认下一步所需依据。",
                ),
            ),
        )


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
        if plan.created_by is None:
            raise AgentApprovalStale("plan creator is no longer available")
        creator = self._session.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.id == plan.created_by,
                WorkspaceMember.workspace_id == self._context.workspace_id,
            )
        )
        if creator is None:
            raise AgentApprovalStale("plan creator is no longer available")
        briefing = BriefingService(
            self._session,
            WorkspaceContext(
                workspace_id=self._context.workspace_id,
                member_id=creator.id,
                role=cast(WorkspaceRole, creator.role.value),
            ),
        ).generate()
        source = self._briefing(plan.briefing_id)
        if briefing.input_fingerprint != source.input_fingerprint:
            return briefing
        return source

    def _approval_snapshot(
        self,
        *,
        briefing_input_fingerprint: str,
        account_id: UUID,
    ) -> AgentPlanApprovalSnapshot:
        return AgentPlanApprovalSnapshot(
            briefing_input_fingerprint=briefing_input_fingerprint,
            account_configuration_version=self._account_version(account_id),
            model_configuration_version=self._model_version(),
            risk_rule_version=self._risk_version(account_id),
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

    def _risk_version(self, account_id: UUID) -> str:
        scans = list(
            self._session.scalars(
                select(RiskScan)
                .where(
                    RiskScan.workspace_id == self._context.workspace_id,
                    RiskScan.account_id == account_id,
                )
                .order_by(RiskScan.id)
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
        contract = self._registry.get(
            "read_account_state",
            version="1.0.0",
        )
        return (
            AllowedToolSummary(
                name=contract.name,
                version=contract.version,
                risk=contract.risk,
                prerequisites=_PLANNING_PREREQUISITES[contract.name],
            ),
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
