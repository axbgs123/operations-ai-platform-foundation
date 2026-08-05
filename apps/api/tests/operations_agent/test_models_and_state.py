from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import CheckConstraint, UniqueConstraint

from app.modules.operations_agent.models import (
    AgentRunStatus,
    AgentStepStatus,
    AgentToolRisk,
)
from app.modules.operations_agent.schemas import AgentPlanDocument, AgentPlanStep
from app.modules.operations_agent.state_machine import (
    InvalidAgentTransition,
    approval_is_current,
    transition_run,
    transition_step,
)
from app.modules.operations_agent.tools import (
    AgentToolContract,
    AgentToolInputError,
    AgentToolOutputError,
    AgentToolRegistry,
)
from app.modules.workspace.permissions import Permission


class SyntheticReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: UUID


class SyntheticReadOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_name: str


SYNTHETIC_READ_TOOL = AgentToolContract(
    name="read_account",
    version="1.0.0",
    risk=AgentToolRisk.READ_ONLY,
    permission=Permission.READ_CONTENT,
    uses_external_api=False,
    retry_policy="safe",
    input_model=SyntheticReadInput,
    output_model=SyntheticReadOutput,
)


def test_run_state_machine_rejects_skipping_plan_approval() -> None:
    with pytest.raises(
        InvalidAgentTransition,
        match="draft.*running",
    ):
        transition_run(AgentRunStatus.DRAFT, AgentRunStatus.RUNNING)


def test_run_state_machine_allows_approved_plan_to_queue() -> None:
    assert (
        transition_run(
            AgentRunStatus.AWAITING_PLAN_APPROVAL,
            AgentRunStatus.QUEUED,
        )
        is AgentRunStatus.QUEUED
    )


def test_step_state_machine_requires_confirmation_before_resuming() -> None:
    assert (
        transition_step(
            AgentStepStatus.RUNNING,
            AgentStepStatus.AWAITING_ACTION_CONFIRMATION,
        )
        is AgentStepStatus.AWAITING_ACTION_CONFIRMATION
    )
    with pytest.raises(
        InvalidAgentTransition,
        match="awaiting_action_confirmation.*succeeded",
    ):
        transition_step(
            AgentStepStatus.AWAITING_ACTION_CONFIRMATION,
            AgentStepStatus.SUCCEEDED,
        )


def test_tool_registry_rejects_unknown_arguments() -> None:
    registry = AgentToolRegistry([SYNTHETIC_READ_TOOL])

    with pytest.raises(AgentToolInputError, match="read_account"):
        registry.validate_call(
            "read_account",
            {"account_id": str(uuid4()), "sql": "select *"},
        )


def test_tool_registry_returns_strict_validated_input() -> None:
    account_id = uuid4()
    registry = AgentToolRegistry([SYNTHETIC_READ_TOOL])

    validated = registry.validate_call(
        "read_account",
        {"account_id": str(account_id)},
    )

    assert validated == SyntheticReadInput(account_id=account_id)


def test_tool_registry_rejects_unknown_output_fields() -> None:
    registry = AgentToolRegistry([SYNTHETIC_READ_TOOL])

    with pytest.raises(AgentToolOutputError, match="read_account"):
        registry.validate_result(
            "read_account",
            {"account_name": "示例账号", "api_key": "must-not-pass"},
        )


def test_tool_registry_rejects_duplicate_tool_name_and_version() -> None:
    with pytest.raises(ValueError, match="duplicate.*read_account.*1.0.0"):
        AgentToolRegistry([SYNTHETIC_READ_TOOL, SYNTHETIC_READ_TOOL])


def test_approval_invalidates_when_plan_fingerprint_changes() -> None:
    assert not approval_is_current(
        approved_fingerprint="a" * 64,
        current_fingerprint="b" * 64,
        approved_tool_catalog_version="agent-tools-v1",
        current_tool_catalog_version="agent-tools-v1",
    )


def test_approval_invalidates_when_tool_catalog_changes() -> None:
    assert not approval_is_current(
        approved_fingerprint="a" * 64,
        current_fingerprint="a" * 64,
        approved_tool_catalog_version="agent-tools-v1",
        current_tool_catalog_version="agent-tools-v2",
    )


def test_plan_document_rejects_unknown_fields_and_duplicate_step_indexes() -> None:
    account_id = uuid4()
    step = AgentPlanStep(
        step_index=0,
        tool_name="read_account",
        tool_version="1.0.0",
        arguments={"account_id": str(account_id)},
        rationale="读取账号安全摘要",
    )

    with pytest.raises(ValueError, match="step indexes must be unique"):
        AgentPlanDocument(
            goal="诊断账号问题",
            platform="douyin",
            account_id=account_id,
            candidate_id="candidate-1",
            input_fingerprint="a" * 64,
            tool_catalog_version="agent-tools-v1",
            steps=(step, step),
        )

    with pytest.raises(ValueError, match="extra"):
        AgentPlanDocument.model_validate(
            {
                "goal": "诊断账号问题",
                "platform": "douyin",
                "account_id": str(account_id),
                "candidate_id": "candidate-1",
                "input_fingerprint": "a" * 64,
                "tool_catalog_version": "agent-tools-v1",
                "steps": [step.model_dump(mode="json")],
                "publish_automatically": True,
            }
        )


def test_agent_tables_define_required_uniqueness_and_fencing_constraints() -> None:
    from app.modules.operations_agent.models import (
        AgentBriefing,
        AgentConfirmation,
        AgentEvent,
        AgentPlan,
        AgentRun,
        AgentRunStep,
    )

    expected_unique_names = {
        "uq_agent_briefings_workspace_input_algorithm",
        "uq_agent_plans_workspace_idempotency",
        "uq_agent_runs_workspace_plan",
        "uq_agent_steps_run_index",
        "uq_agent_confirmations_run_step_action",
        "uq_agent_events_workspace_idempotency",
    }
    tables = (
        AgentBriefing.__table__,
        AgentPlan.__table__,
        AgentRun.__table__,
        AgentRunStep.__table__,
        AgentConfirmation.__table__,
        AgentEvent.__table__,
    )
    actual_unique_names = {
        constraint.name
        for table in tables
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert expected_unique_names <= actual_unique_names

    check_sql = " ".join(
        str(constraint.sqltext)
        for table in tables
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    )
    assert "operation_version >= 1" in check_sql
    assert "step_index >= 0" in check_sql
