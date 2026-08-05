from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import WorkspaceContext
from app.modules.content.account_models import Platform, PlatformAccount
from app.modules.operations_agent.executor import (
    AgentClaimLost,
    AgentExecutor,
    AgentRecovery,
    ToolInvocation,
    ToolObservation,
)
from app.modules.operations_agent.models import (
    AgentRun,
    AgentRunStep,
    AgentRunStatus,
    AgentStepStatus,
    AgentToolRisk,
)
from app.modules.operations_agent.tools import (
    AgentToolContract,
    AgentToolRegistry,
)
from app.modules.workspace.models import WorkspaceMember
from app.modules.workspace.permissions import Permission
from tests.imports.helpers import configured_client, create_workspace_account
from tests.operations_agent.test_planning_api import _create_plan


class SyntheticToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: UUID


class SyntheticToolOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    safe_summary: str


@dataclass
class RecordingToolRunner:
    observation: ToolObservation
    calls: list[ToolInvocation] = field(default_factory=list)

    def invoke(self, invocation: ToolInvocation) -> ToolObservation:
        self.calls.append(invocation)
        return self.observation


@dataclass(frozen=True)
class ExecutorFixture:
    executor: AgentExecutor
    recovery: AgentRecovery
    factory: sessionmaker[Session]
    context: WorkspaceContext
    run_id: UUID
    runner: RecordingToolRunner
    client: Any
    csrf: str


@contextmanager
def _executor_fixture(
    *,
    risk: AgentToolRisk = AgentToolRisk.READ_ONLY,
    retry_policy: Literal["safe", "never", "manual"] = "safe",
) -> Iterator[ExecutorFixture]:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        plan = _create_plan(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
        )
        approved = client.post(
            (
                f"/v1/workspaces/{workspace_id}/agent/plans/"
                f"{plan['id']}/approve"
            ),
            headers={"X-CSRF-Token": csrf},
        )
        assert approved.status_code == 200, approved.text
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as session:
            admin = session.query(WorkspaceMember).filter_by(
                workspace_id=UUID(workspace_id),
                role="admin",
            ).one()
            context = WorkspaceContext(
                workspace_id=UUID(workspace_id),
                member_id=admin.id,
                role="admin",
            )
        registry = AgentToolRegistry(
            [
                AgentToolContract(
                    name="read_account_state",
                    version="1.0.0",
                    risk=risk,
                    permission=Permission.READ_CONTENT,
                    uses_external_api=False,
                    retry_policy=retry_policy,
                    input_model=SyntheticToolInput,
                    output_model=SyntheticToolOutput,
                )
            ],
            catalog_version="agent-tools-v1",
        )
        runner = RecordingToolRunner(
            ToolObservation(
                status="success",
                safe_summary="合成工具执行成功",
            )
        )
        executor = AgentExecutor(
            factory,
            registry=registry,
            tool_runner=runner,
        )
        run = executor.create_run(UUID(plan["id"]), context=context)
        yield ExecutorFixture(
            executor=executor,
            recovery=AgentRecovery(factory, registry=registry),
            factory=factory,
            context=context,
            run_id=run.id,
            runner=runner,
            client=client,
            csrf=csrf,
        )


def test_executor_stops_at_confirmation_without_calling_tool() -> None:
    with _executor_fixture(
        risk=AgentToolRisk.PROTECTED_WRITE,
    ) as fixture:
        claim = fixture.executor.claim_next_step(fixture.run_id)

        result = fixture.executor.execute_claim(claim)

        assert result.run_status is AgentRunStatus.AWAITING_ACTION_CONFIRMATION
        assert fixture.runner.calls == []
        with fixture.factory() as session:
            run = session.get(AgentRun, fixture.run_id)
            assert run is not None
            assert run.status is AgentRunStatus.AWAITING_ACTION_CONFIRMATION


def test_old_worker_cannot_publish_after_run_is_cancelled() -> None:
    with _executor_fixture() as fixture:
        claim = fixture.executor.claim_next_step(fixture.run_id)
        fixture.executor.cancel(
            fixture.run_id,
            context=fixture.context,
        )

        with pytest.raises(AgentClaimLost):
            fixture.executor.publish_result(
                claim,
                ToolObservation(
                    status="success",
                    safe_summary="旧 Worker 不应写入",
                ),
            )


def test_platform_account_scope_is_revalidated_before_publish() -> None:
    with _executor_fixture() as fixture:
        claim = fixture.executor.claim_next_step(fixture.run_id)
        with fixture.factory.begin() as session:
            run = session.get(AgentRun, fixture.run_id)
            assert run is not None
            account = session.get(PlatformAccount, run.account_id)
            assert account is not None
            account.platform = Platform.XIAOHONGSHU

        with pytest.raises(AgentClaimLost, match="account scope changed"):
            fixture.executor.publish_result(
                claim,
                ToolObservation(
                    status="success",
                    safe_summary="平台范围已变化，不应写入",
                ),
            )
        fixture.executor.fail_invalidated(
            fixture.run_id,
            claim=claim,
        )
        with fixture.factory() as session:
            run = session.get(AgentRun, fixture.run_id)
            assert run is not None
            assert run.status is AgentRunStatus.FAILED
            assert run.safe_error_code == "AGENT_EXECUTION_CONTEXT_CHANGED"


def test_provider_unknown_is_not_automatically_retried() -> None:
    with _executor_fixture() as fixture:
        claim = fixture.executor.claim_next_step(fixture.run_id)

        fixture.executor.publish_provider_unknown(claim)

        with fixture.factory() as session:
            run = session.get(AgentRun, fixture.run_id)
            assert run is not None
            assert run.status is AgentRunStatus.PROVIDER_OUTCOME_UNKNOWN
            step = session.query(AgentRunStep).filter_by(run_id=run.id).one()
            assert step.status is AgentStepStatus.PROVIDER_OUTCOME_UNKNOWN
            assert step.completed_at is not None
        assert fixture.recovery.find_recoverable_steps() == ()
        with pytest.raises(
            ValueError,
            match="PROVIDER_OUTCOME_UNKNOWN_REQUIRES_REVIEW",
        ):
            fixture.executor.retry(
                fixture.run_id,
                context=fixture.context,
                idempotency_key="unsafe-unknown-retry",
            )


def test_expired_safe_claim_is_recovered_for_another_worker() -> None:
    with _executor_fixture(retry_policy="safe") as fixture:
        claim = fixture.executor.claim_next_step(fixture.run_id)
        with fixture.factory.begin() as session:
            run = session.get(AgentRun, fixture.run_id)
            assert run is not None
            run.lease_expires_at = claim.lease_expires_at - timedelta(minutes=2)

        assert fixture.recovery.recover_expired() == (fixture.run_id,)

        replacement = fixture.executor.claim_next_step(fixture.run_id)
        assert replacement.claim_token != claim.claim_token
        with pytest.raises(AgentClaimLost):
            fixture.executor.publish_result(
                claim,
                ToolObservation(status="success", safe_summary="陈旧结果"),
            )


def test_manual_retry_is_limited_to_manual_policy() -> None:
    with _executor_fixture(retry_policy="manual") as fixture:
        claim = fixture.executor.claim_next_step(fixture.run_id)
        fixture.executor.publish_result(
            claim,
            ToolObservation(
                status="error",
                safe_summary="可人工重试的合成失败",
                error_code="SYNTHETIC_TRANSIENT_FAILURE",
            ),
        )

        retried = fixture.executor.retry(
            fixture.run_id,
            context=fixture.context,
            idempotency_key="manual-retry-1",
        )

        assert retried.status is AgentRunStatus.QUEUED
        with fixture.factory() as session:
            step = session.query(AgentRunStep).filter_by(
                run_id=fixture.run_id,
            ).one()
            assert step.status is AgentStepStatus.PENDING
            assert step.attempt_count == 1
        replacement = fixture.executor.claim_next_step(fixture.run_id)
        assert replacement.step_id == claim.step_id


def test_run_apis_are_readable_and_cancel_requires_csrf() -> None:
    with _executor_fixture() as fixture:
        workspace_id = fixture.context.workspace_id

        listed = fixture.client.get(
            f"/v1/workspaces/{workspace_id}/agent/runs",
        )
        assert listed.status_code == 200, listed.text
        assert listed.json()["items"][0]["id"] == str(fixture.run_id)

        detail = fixture.client.get(
            f"/v1/workspaces/{workspace_id}/agent/runs/{fixture.run_id}",
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["steps"][0]["tool_name"] == "read_account_state"
        assert "input_envelope" not in detail.text

        rejected = fixture.client.post(
            f"/v1/workspaces/{workspace_id}/agent/runs/{fixture.run_id}/cancel",
            headers={"Idempotency-Key": "cancel-without-csrf"},
        )
        assert rejected.status_code == 403

        cancelled = fixture.client.post(
            f"/v1/workspaces/{workspace_id}/agent/runs/{fixture.run_id}/cancel",
            headers={
                "Idempotency-Key": "cancel-1",
                "X-CSRF-Token": fixture.csrf,
            },
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"


def test_worker_registers_agent_execution_and_recovery_schedule() -> None:
    import importlib
    import sys

    module = importlib.import_module("app.worker")
    try:
        assert "app.modules.operations_agent.tasks" in module.celery_app.conf.imports
        recovery = module.celery_app.conf.beat_schedule[
            "recover-pending-operations-agent-runs"
        ]
        assert recovery["task"] == "operations_agent.recover_pending"
        assert recovery["schedule"] == 30.0
    finally:
        sys.modules.pop("app.worker", None)
