from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import secrets
from typing import Literal, Protocol, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import utc_now
from app.core.security import WorkspaceContext, WorkspaceRole
from app.modules.content.account_models import PlatformAccount
from app.modules.operations_agent.models import (
    AgentConfirmation,
    AgentConfirmationStatus,
    AgentEvent,
    AgentPlan,
    AgentRun,
    AgentRunStatus,
    AgentRunStep,
    AgentStepStatus,
    AgentToolRisk,
)
from app.modules.operations_agent.planning import AgentApprovalStale, PlanService
from app.modules.operations_agent.schemas import StoredAgentPlanDocument
from app.modules.operations_agent.state_machine import (
    transition_run,
    transition_step,
)
from app.modules.operations_agent.tools import (
    AgentToolContract,
    AgentToolInputError,
    AgentToolRegistry,
)
from app.modules.workspace.models import WorkspaceMember
from app.modules.workspace.permissions import (
    Permission,
    PermissionDenied,
    require_permission,
)


class AgentClaimLost(RuntimeError):
    pass


class AgentClaimUnavailable(RuntimeError):
    pass


class AgentExecutionInvalidated(AgentClaimLost):
    pass


@dataclass(frozen=True)
class StepClaim:
    run_id: UUID
    step_id: UUID
    step_index: int
    claim_token: str
    operation_version: int
    lease_expires_at: datetime


class ToolObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["success", "denied", "error", "cancelled", "unknown"]
    safe_summary: str = Field(min_length=1, max_length=500)
    artifact_refs: tuple[str, ...] = Field(default=(), max_length=32)
    evidence_refs: tuple[str, ...] = Field(default=(), max_length=32)
    error_code: str | None = Field(default=None, max_length=100)
    next_valid_actions: tuple[str, ...] = Field(default=(), max_length=16)


@dataclass(frozen=True)
class ToolInvocation:
    workspace_id: UUID
    run_id: UUID
    step_id: UUID
    account_id: UUID
    platform: str
    actor_id: UUID
    tool_name: str
    tool_version: str
    arguments: Mapping[str, object]


class AgentToolRunner(Protocol):
    def invoke(self, invocation: ToolInvocation) -> ToolObservation: ...


class UnavailableToolRunner:
    def invoke(self, invocation: ToolInvocation) -> ToolObservation:
        del invocation
        return ToolObservation(
            status="error",
            safe_summary="当前工具尚未接入可执行实现。",
            error_code="AGENT_TOOL_UNAVAILABLE",
            next_valid_actions=("review_plan",),
        )


class ExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    step_id: UUID
    run_status: AgentRunStatus
    step_status: AgentStepStatus
    observation: ToolObservation | None = None


Clock = Callable[[], datetime]


class AgentExecutor:
    def __init__(
        self,
        factory: sessionmaker[Session],
        *,
        registry: AgentToolRegistry,
        tool_runner: AgentToolRunner | None = None,
        lease_duration: timedelta = timedelta(seconds=60),
        clock: Clock = utc_now,
    ) -> None:
        self._factory = factory
        self._registry = registry
        self._tool_runner = tool_runner or UnavailableToolRunner()
        self._lease_duration = lease_duration
        self._clock = clock

    def create_run(
        self,
        plan_id: UUID,
        *,
        context: WorkspaceContext,
    ) -> AgentRun:
        require_permission(context.role, Permission.WRITE_CONTENT)
        with self._factory.begin() as session:
            plan_service = PlanService(
                session,
                context,
                registry=self._registry,
            )
            plan_service.assert_approval_current(plan_id)
            plan = session.scalar(
                select(AgentPlan)
                .where(
                    AgentPlan.id == plan_id,
                    AgentPlan.workspace_id == context.workspace_id,
                )
                .with_for_update()
            )
            if plan is None:
                raise LookupError("plan not found")
            existing = session.scalar(
                select(AgentRun).where(
                    AgentRun.workspace_id == context.workspace_id,
                    AgentRun.plan_id == plan.id,
                )
            )
            if existing is not None:
                return existing
            stored = StoredAgentPlanDocument.model_validate(plan.document)
            run = AgentRun(
                workspace_id=context.workspace_id,
                plan_id=plan.id,
                account_id=plan.account_id,
                platform=plan.platform,
                status=AgentRunStatus.QUEUED,
                current_step_index=0,
                created_by=context.member_id,
            )
            session.add(run)
            session.flush()
            for plan_step in stored.plan.steps:
                contract = self._registry.get(
                    plan_step.tool_name,
                    version=plan_step.tool_version,
                )
                arguments = self._registry.validate_call(
                    plan_step.tool_name,
                    plan_step.arguments,
                    version=plan_step.tool_version,
                ).model_dump(mode="json")
                self._assert_account_scope(arguments, plan.account_id)
                session.add(
                    AgentRunStep(
                        workspace_id=context.workspace_id,
                        run_id=run.id,
                        step_index=plan_step.step_index,
                        tool_name=contract.name,
                        tool_version=contract.version,
                        tool_risk=contract.risk,
                        input_fingerprint=_fingerprint(arguments),
                        input_envelope={
                            "arguments": arguments,
                            "rationale": plan_step.rationale,
                        },
                        status=AgentStepStatus.PENDING,
                    )
                )
            self._append_event(
                session,
                run,
                event_type="run_created",
                idempotency_key=f"run-created:{run.id}",
            )
            session.flush()
            return run

    def claim_next_step(self, run_id: UUID) -> StepClaim:
        with self._factory.begin() as session:
            run = self._run_for_update(session, run_id)
            if run.status not in {
                AgentRunStatus.QUEUED,
                AgentRunStatus.RUNNING,
            }:
                raise AgentClaimUnavailable("run is not claimable")
            if run.claim_token is not None:
                raise AgentClaimUnavailable("run already has an active claim")
            context = self._execution_context(session, run)
            step = self._current_step_for_update(session, run)
            if step.status is not AgentStepStatus.PENDING:
                raise AgentClaimUnavailable("step is not pending")
            contract = self._validated_contract(
                session=session,
                context=context,
                run=run,
                step=step,
            )
            self._assert_approval_current(session, context, run)
            self._assert_tool_permission(context, contract)
            if run.status is AgentRunStatus.QUEUED:
                run.status = transition_run(
                    run.status,
                    AgentRunStatus.RUNNING,
                )
            step.status = transition_step(
                step.status,
                AgentStepStatus.RUNNING,
            )
            step.attempt_count += 1
            step.started_at = self._now()
            token = secrets.token_urlsafe(32)
            lease_expires_at = self._now() + self._lease_duration
            run.claim_token = token
            run.lease_expires_at = lease_expires_at
            session.flush()
            claim = StepClaim(
                run_id=run.id,
                step_id=step.id,
                step_index=step.step_index,
                claim_token=token,
                operation_version=run.operation_version,
                lease_expires_at=lease_expires_at,
            )
            self._append_event(
                session,
                run,
                event_type="step_claimed",
                idempotency_key=(
                    f"step-claimed:{step.id}:{step.attempt_count}"
                ),
                step_id=step.id,
            )
            return claim

    def execute_claim(self, claim: StepClaim) -> ExecutionResult:
        with self._factory.begin() as session:
            run, step, context, contract = self._validated_claim(
                session,
                claim,
            )
            if contract.risk is AgentToolRisk.PROTECTED_WRITE:
                confirmation = self._create_confirmation(
                    session,
                    run,
                    step,
                    contract,
                )
                step.status = transition_step(
                    step.status,
                    AgentStepStatus.AWAITING_ACTION_CONFIRMATION,
                )
                run.status = transition_run(
                    run.status,
                    AgentRunStatus.AWAITING_ACTION_CONFIRMATION,
                )
                run.claim_token = None
                run.lease_expires_at = None
                self._append_event(
                    session,
                    run,
                    event_type="action_confirmation_requested",
                    idempotency_key=(
                        f"confirmation-requested:{confirmation.id}"
                    ),
                    step_id=step.id,
                    safe_payload={
                        "confirmation_id": str(confirmation.id),
                        "tool_name": contract.name,
                        "tool_version": contract.version,
                    },
                )
                session.flush()
                return ExecutionResult(
                    run_id=run.id,
                    step_id=step.id,
                    run_status=run.status,
                    step_status=step.status,
                )
            invocation = ToolInvocation(
                workspace_id=run.workspace_id,
                run_id=run.id,
                step_id=step.id,
                account_id=run.account_id,
                platform=run.platform.value,
                actor_id=cast(UUID, context.member_id),
                tool_name=step.tool_name,
                tool_version=step.tool_version,
                arguments=self._arguments(step),
            )
        try:
            observation = self._tool_runner.invoke(invocation)
        except Exception:
            observation = ToolObservation(
                status="error",
                safe_summary="工具执行失败，未保存原始异常内容。",
                error_code="AGENT_TOOL_EXECUTION_FAILED",
                next_valid_actions=("review_error",),
            )
        return self.publish_result(claim, observation)

    def publish_result(
        self,
        claim: StepClaim,
        observation: ToolObservation,
    ) -> ExecutionResult:
        with self._factory.begin() as session:
            run, step, _, _ = self._validated_claim(session, claim)
            if observation.status == "success":
                step.status = transition_step(
                    step.status,
                    AgentStepStatus.SUCCEEDED,
                )
                step.result_envelope = observation.model_dump(mode="json")
                step.completed_at = self._now()
                next_step = session.scalar(
                    select(AgentRunStep).where(
                        AgentRunStep.run_id == run.id,
                        AgentRunStep.step_index == step.step_index + 1,
                    )
                )
                if next_step is None:
                    run.status = transition_run(
                        run.status,
                        AgentRunStatus.SUCCEEDED,
                    )
                    run.completed_at = self._now()
                else:
                    run.current_step_index = next_step.step_index
            elif observation.status == "unknown":
                step.status = transition_step(
                    step.status,
                    AgentStepStatus.PROVIDER_OUTCOME_UNKNOWN,
                )
                step.safe_error_code = (
                    observation.error_code or "PROVIDER_OUTCOME_UNKNOWN"
                )
                run.status = transition_run(
                    run.status,
                    AgentRunStatus.PROVIDER_OUTCOME_UNKNOWN,
                )
                run.safe_error_code = step.safe_error_code
                step.completed_at = self._now()
                run.completed_at = self._now()
            elif observation.status == "cancelled":
                step.status = transition_step(
                    step.status,
                    AgentStepStatus.CANCELLED,
                )
                run.status = transition_run(
                    run.status,
                    AgentRunStatus.CANCELLED,
                )
                step.completed_at = self._now()
                run.completed_at = self._now()
            else:
                step.status = transition_step(
                    step.status,
                    AgentStepStatus.FAILED,
                )
                step.safe_error_code = (
                    observation.error_code or "AGENT_TOOL_FAILED"
                )
                step.completed_at = self._now()
                run.status = transition_run(
                    run.status,
                    AgentRunStatus.FAILED,
                )
                run.safe_error_code = step.safe_error_code
                run.completed_at = self._now()
            step.result_envelope = observation.model_dump(mode="json")
            run.claim_token = None
            run.lease_expires_at = None
            self._append_event(
                session,
                run,
                event_type="step_result_published",
                idempotency_key=(
                    f"step-result:{step.id}:{step.attempt_count}"
                ),
                step_id=step.id,
                safe_payload={
                    "status": observation.status,
                    "error_code": observation.error_code,
                },
            )
            session.flush()
            return ExecutionResult(
                run_id=run.id,
                step_id=step.id,
                run_status=run.status,
                step_status=step.status,
                observation=observation,
            )

    def publish_provider_unknown(self, claim: StepClaim) -> ExecutionResult:
        return self.publish_result(
            claim,
            ToolObservation(
                status="unknown",
                safe_summary=(
                    "供应商请求结果无法确认，系统不会自动重试。"
                ),
                error_code="PROVIDER_OUTCOME_UNKNOWN",
                next_valid_actions=("manual_review",),
            ),
        )

    def cancel(
        self,
        run_id: UUID,
        *,
        context: WorkspaceContext,
        idempotency_key: str | None = None,
    ) -> AgentRun:
        require_permission(context.role, Permission.WRITE_CONTENT)
        with self._factory.begin() as session:
            run = self._run_for_update(
                session,
                run_id,
                workspace_id=context.workspace_id,
            )
            if run.status in {
                AgentRunStatus.SUCCEEDED,
                AgentRunStatus.REJECTED,
                AgentRunStatus.CANCELLED,
                AgentRunStatus.FAILED,
                AgentRunStatus.PROVIDER_OUTCOME_UNKNOWN,
            }:
                return run
            step = self._current_step_for_update(session, run)
            if step.status in {
                AgentStepStatus.PENDING,
                AgentStepStatus.RUNNING,
                AgentStepStatus.AWAITING_ACTION_CONFIRMATION,
            }:
                step.status = transition_step(
                    step.status,
                    AgentStepStatus.CANCELLED,
                )
                step.completed_at = self._now()
            run.status = transition_run(
                run.status,
                AgentRunStatus.CANCELLED,
            )
            run.claim_token = None
            run.lease_expires_at = None
            run.completed_at = self._now()
            self._append_event(
                session,
                run,
                event_type="run_cancelled",
                idempotency_key=(
                    f"run-cancelled:{run.id}:{idempotency_key}"
                    if idempotency_key
                    else f"run-cancelled:{run.id}"
                ),
            )
            session.flush()
            return run

    def retry(
        self,
        run_id: UUID,
        *,
        context: WorkspaceContext,
        idempotency_key: str,
    ) -> AgentRun:
        require_permission(context.role, Permission.WRITE_CONTENT)
        with self._factory.begin() as session:
            run = self._run_for_update(
                session,
                run_id,
                workspace_id=context.workspace_id,
            )
            event_key = f"run-manual-retry:{run.id}:{idempotency_key}"
            existing = session.scalar(
                select(AgentEvent.id).where(
                    AgentEvent.workspace_id == context.workspace_id,
                    AgentEvent.idempotency_key == event_key,
                )
            )
            if existing is not None:
                return run
            if run.status is AgentRunStatus.PROVIDER_OUTCOME_UNKNOWN:
                raise ValueError("PROVIDER_OUTCOME_UNKNOWN_REQUIRES_REVIEW")
            if run.status not in {
                AgentRunStatus.FAILED,
                AgentRunStatus.COMPENSATION_REQUIRED,
            }:
                raise ValueError("AGENT_RUN_NOT_MANUALLY_RETRYABLE")
            step = self._current_step_for_update(session, run)
            contract = self._registry.get(
                step.tool_name,
                version=step.tool_version,
            )
            if contract.retry_policy != "manual":
                raise ValueError("AGENT_TOOL_MANUAL_RETRY_NOT_ALLOWED")
            require_permission(context.role, contract.permission)
            if step.status not in {
                AgentStepStatus.FAILED,
                AgentStepStatus.COMPENSATION_REQUIRED,
            }:
                raise ValueError("AGENT_STEP_NOT_MANUALLY_RETRYABLE")
            step.status = transition_step(
                step.status,
                AgentStepStatus.PENDING,
            )
            step.result_envelope = None
            step.safe_error_code = None
            step.started_at = None
            step.completed_at = None
            run.status = transition_run(run.status, AgentRunStatus.QUEUED)
            run.safe_error_code = None
            run.completed_at = None
            run.claim_token = None
            run.lease_expires_at = None
            self._append_event(
                session,
                run,
                event_type="run_manual_retry",
                idempotency_key=event_key,
                step_id=step.id,
                safe_payload={
                    "attempt_count": step.attempt_count,
                    "tool_name": step.tool_name,
                },
            )
            session.flush()
            return run

    def fail_invalidated(
        self,
        run_id: UUID,
        *,
        claim: StepClaim | None = None,
    ) -> None:
        with self._factory.begin() as session:
            run = self._run_for_update(session, run_id)
            if run.status not in {
                AgentRunStatus.QUEUED,
                AgentRunStatus.RUNNING,
            }:
                return
            if claim is not None and (
                run.claim_token != claim.claim_token
                or run.operation_version != claim.operation_version
            ):
                return
            step = self._current_step_for_update(session, run)
            if step.status not in {
                AgentStepStatus.PENDING,
                AgentStepStatus.RUNNING,
            }:
                return
            step.status = transition_step(
                step.status,
                AgentStepStatus.FAILED,
            )
            step.safe_error_code = "AGENT_EXECUTION_CONTEXT_CHANGED"
            step.completed_at = self._now()
            run.status = transition_run(
                run.status,
                AgentRunStatus.FAILED,
            )
            run.safe_error_code = step.safe_error_code
            run.completed_at = self._now()
            run.claim_token = None
            run.lease_expires_at = None
            self._append_event(
                session,
                run,
                event_type="run_execution_context_invalidated",
                idempotency_key=(
                    f"run-context-invalidated:{run.id}:"
                    f"{run.operation_version}"
                ),
                step_id=step.id,
                safe_payload={
                    "error_code": step.safe_error_code,
                    "step_index": step.step_index,
                },
            )

    def _validated_claim(
        self,
        session: Session,
        claim: StepClaim,
    ) -> tuple[
        AgentRun,
        AgentRunStep,
        WorkspaceContext,
        AgentToolContract,
    ]:
        run = self._run_for_update(session, claim.run_id)
        step = session.scalar(
            select(AgentRunStep)
            .where(
                AgentRunStep.id == claim.step_id,
                AgentRunStep.run_id == run.id,
            )
            .with_for_update()
        )
        if (
            step is None
            or step.step_index != claim.step_index
            or run.status is not AgentRunStatus.RUNNING
            or step.status is not AgentStepStatus.RUNNING
            or run.claim_token != claim.claim_token
            or run.operation_version != claim.operation_version
            or run.lease_expires_at is None
            or run.lease_expires_at < self._now()
        ):
            raise AgentClaimLost("agent step claim is no longer valid")
        context = self._execution_context(session, run)
        contract = self._validated_contract(
            session=session,
            context=context,
            run=run,
            step=step,
        )
        self._assert_approval_current(session, context, run)
        self._assert_tool_permission(context, contract)
        return run, step, context, contract

    def _validated_contract(
        self,
        *,
        session: Session,
        context: WorkspaceContext,
        run: AgentRun,
        step: AgentRunStep,
    ) -> AgentToolContract:
        if run.workspace_id != context.workspace_id:
            raise AgentExecutionInvalidated("workspace scope changed")
        account = session.scalar(
            select(PlatformAccount).where(
                PlatformAccount.id == run.account_id,
                PlatformAccount.workspace_id == run.workspace_id,
                PlatformAccount.platform == run.platform,
            )
        )
        if account is None:
            raise AgentExecutionInvalidated("account scope changed")
        plan = step.input_envelope
        arguments = plan.get("arguments")
        try:
            contract = self._registry.get(
                step.tool_name,
                version=step.tool_version,
            )
        except AgentToolInputError as error:
            raise AgentExecutionInvalidated(
                "tool version is unavailable"
            ) from error
        if contract.risk is not step.tool_risk:
            raise AgentExecutionInvalidated("tool risk contract changed")
        try:
            validated = self._registry.validate_call(
                step.tool_name,
                arguments,
                version=step.tool_version,
            ).model_dump(mode="json")
        except AgentToolInputError as error:
            raise AgentExecutionInvalidated(
                "tool arguments are no longer valid"
            ) from error
        self._assert_account_scope(validated, run.account_id)
        return contract

    def _assert_approval_current(
        self,
        session: Session,
        context: WorkspaceContext,
        run: AgentRun,
    ) -> None:
        try:
            PlanService(
                session,
                context,
                registry=self._registry,
            ).assert_approval_current(run.plan_id)
        except AgentApprovalStale as error:
            raise AgentExecutionInvalidated(
                "plan approval changed"
            ) from error

    @staticmethod
    def _assert_tool_permission(
        context: WorkspaceContext,
        contract: AgentToolContract,
    ) -> None:
        try:
            require_permission(context.role, contract.permission)
        except PermissionDenied as error:
            raise AgentExecutionInvalidated(
                "tool permission is no longer available"
            ) from error

    def _execution_context(
        self,
        session: Session,
        run: AgentRun,
    ) -> WorkspaceContext:
        if run.created_by is None:
            raise AgentExecutionInvalidated("run actor is unavailable")
        member = session.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.id == run.created_by,
                WorkspaceMember.workspace_id == run.workspace_id,
                WorkspaceMember.revoked_at.is_(None),
            )
        )
        if member is None:
            raise AgentExecutionInvalidated("run actor is unavailable")
        if member.role.value not in {"admin", "editor"}:
            raise AgentExecutionInvalidated(
                "run actor no longer has execution permission"
            )
        return WorkspaceContext(
            workspace_id=run.workspace_id,
            member_id=member.id,
            role=cast(WorkspaceRole, member.role.value),
        )

    def _create_confirmation(
        self,
        session: Session,
        run: AgentRun,
        step: AgentRunStep,
        contract: AgentToolContract,
    ) -> AgentConfirmation:
        arguments = self._arguments(step)
        action_fingerprint = _fingerprint(
            {
                "run_id": str(run.id),
                "step_id": str(step.id),
                "tool_name": step.tool_name,
                "tool_version": step.tool_version,
                "arguments": arguments,
            }
        )
        existing = session.scalar(
            select(AgentConfirmation).where(
                AgentConfirmation.run_id == run.id,
                AgentConfirmation.step_id == step.id,
                AgentConfirmation.action_fingerprint
                == action_fingerprint,
            )
        )
        if existing is not None:
            return existing
        confirmation = AgentConfirmation(
            workspace_id=run.workspace_id,
            run_id=run.id,
            step_id=step.id,
            action_fingerprint=action_fingerprint,
            action_summary={
                "tool_name": contract.name,
                "tool_version": contract.version,
                "risk": contract.risk.value,
                "argument_keys": sorted(arguments),
            },
            status=AgentConfirmationStatus.PENDING,
            requested_by=run.created_by,
        )
        session.add(confirmation)
        return confirmation

    def _run_for_update(
        self,
        session: Session,
        run_id: UUID,
        *,
        workspace_id: UUID | None = None,
    ) -> AgentRun:
        filters = [AgentRun.id == run_id]
        if workspace_id is not None:
            filters.append(AgentRun.workspace_id == workspace_id)
        run = session.scalar(
            select(AgentRun).where(*filters).with_for_update()
        )
        if run is None:
            raise LookupError("run not found")
        return run

    @staticmethod
    def _current_step_for_update(
        session: Session,
        run: AgentRun,
    ) -> AgentRunStep:
        step = session.scalar(
            select(AgentRunStep)
            .where(
                AgentRunStep.run_id == run.id,
                AgentRunStep.step_index == run.current_step_index,
            )
            .with_for_update()
        )
        if step is None:
            raise LookupError("run step not found")
        return step

    @staticmethod
    def _arguments(step: AgentRunStep) -> dict[str, object]:
        arguments = step.input_envelope.get("arguments")
        if not isinstance(arguments, dict):
            raise AgentClaimLost("step arguments are invalid")
        return dict(arguments)

    @staticmethod
    def _assert_account_scope(
        arguments: Mapping[str, object],
        account_id: UUID,
    ) -> None:
        raw_account_id = arguments.get("account_id")
        if raw_account_id is not None and UUID(str(raw_account_id)) != account_id:
            raise AgentExecutionInvalidated("step account scope changed")

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("executor clock must be timezone-aware")
        return value.astimezone(UTC)

    @staticmethod
    def _append_event(
        session: Session,
        run: AgentRun,
        *,
        event_type: str,
        idempotency_key: str,
        step_id: UUID | None = None,
        safe_payload: dict[str, object] | None = None,
    ) -> None:
        existing = session.scalar(
            select(AgentEvent.id).where(
                AgentEvent.workspace_id == run.workspace_id,
                AgentEvent.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return
        session.add(
            AgentEvent(
                workspace_id=run.workspace_id,
                event_type=event_type,
                idempotency_key=idempotency_key,
                safe_payload=safe_payload or {"run_id": str(run.id)},
                run_id=run.id,
                step_id=step_id,
                actor_id=run.created_by,
            )
        )


class AgentRecovery:
    def __init__(
        self,
        factory: sessionmaker[Session],
        *,
        registry: AgentToolRegistry,
        clock: Clock = utc_now,
    ) -> None:
        self._factory = factory
        self._registry = registry
        self._clock = clock

    def find_recoverable_steps(self) -> tuple[UUID, ...]:
        now = self._now()
        with self._factory() as session:
            runs = list(
                session.scalars(
                    select(AgentRun).where(
                        AgentRun.status == AgentRunStatus.RUNNING,
                        AgentRun.claim_token.is_not(None),
                        AgentRun.lease_expires_at < now,
                    )
                )
            )
            recoverable: list[UUID] = []
            for run in runs:
                step = session.scalar(
                    select(AgentRunStep).where(
                        AgentRunStep.run_id == run.id,
                        AgentRunStep.step_index == run.current_step_index,
                        AgentRunStep.status == AgentStepStatus.RUNNING,
                    )
                )
                if step is None:
                    continue
                contract = self._registry.get(
                    step.tool_name,
                    version=step.tool_version,
                )
                if contract.retry_policy == "safe":
                    recoverable.append(run.id)
            return tuple(sorted(recoverable, key=str))

    def recover_expired(self) -> tuple[UUID, ...]:
        recovered: list[UUID] = []
        for run_id in self.find_recoverable_steps():
            with self._factory.begin() as session:
                run = session.scalar(
                    select(AgentRun)
                    .where(AgentRun.id == run_id)
                    .with_for_update()
                )
                if (
                    run is None
                    or run.status is not AgentRunStatus.RUNNING
                    or run.lease_expires_at is None
                    or run.lease_expires_at >= self._now()
                ):
                    continue
                step = session.scalar(
                    select(AgentRunStep)
                    .where(
                        AgentRunStep.run_id == run.id,
                        AgentRunStep.step_index == run.current_step_index,
                    )
                    .with_for_update()
                )
                if step is None or step.status is not AgentStepStatus.RUNNING:
                    continue
                contract = self._registry.get(
                    step.tool_name,
                    version=step.tool_version,
                )
                if contract.retry_policy != "safe":
                    continue
                step.status = AgentStepStatus.PENDING
                run.claim_token = None
                run.lease_expires_at = None
                AgentExecutor._append_event(
                    session,
                    run,
                    event_type="expired_claim_recovered",
                    idempotency_key=(
                        f"claim-recovered:{step.id}:{step.attempt_count}"
                    ),
                    step_id=step.id,
                )
                recovered.append(run.id)
        return tuple(recovered)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("recovery clock must be timezone-aware")
        return value.astimezone(UTC)


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
