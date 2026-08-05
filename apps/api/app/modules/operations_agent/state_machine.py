from collections.abc import Mapping
from enum import StrEnum

from app.modules.operations_agent.models import AgentRunStatus, AgentStepStatus


class InvalidAgentTransition(ValueError):
    pass


_RUN_TRANSITIONS: Mapping[AgentRunStatus, frozenset[AgentRunStatus]] = {
    AgentRunStatus.DRAFT: frozenset(
        {
            AgentRunStatus.AWAITING_PLAN_APPROVAL,
            AgentRunStatus.CANCELLED,
        }
    ),
    AgentRunStatus.AWAITING_PLAN_APPROVAL: frozenset(
        {
            AgentRunStatus.QUEUED,
            AgentRunStatus.REJECTED,
            AgentRunStatus.CANCELLED,
        }
    ),
    AgentRunStatus.QUEUED: frozenset(
        {
            AgentRunStatus.RUNNING,
            AgentRunStatus.CANCELLED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CONFIGURATION_REQUIRED,
        }
    ),
    AgentRunStatus.RUNNING: frozenset(
        {
            AgentRunStatus.AWAITING_ACTION_CONFIRMATION,
            AgentRunStatus.SUCCEEDED,
            AgentRunStatus.CANCELLED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CONFIGURATION_REQUIRED,
            AgentRunStatus.COMPENSATION_REQUIRED,
            AgentRunStatus.PROVIDER_OUTCOME_UNKNOWN,
        }
    ),
    AgentRunStatus.AWAITING_ACTION_CONFIRMATION: frozenset(
        {
            AgentRunStatus.QUEUED,
            AgentRunStatus.REJECTED,
            AgentRunStatus.CANCELLED,
        }
    ),
    AgentRunStatus.CONFIGURATION_REQUIRED: frozenset(
        {
            AgentRunStatus.QUEUED,
            AgentRunStatus.CANCELLED,
        }
    ),
    AgentRunStatus.COMPENSATION_REQUIRED: frozenset(
        {
            AgentRunStatus.QUEUED,
            AgentRunStatus.FAILED,
        }
    ),
    AgentRunStatus.SUCCEEDED: frozenset(),
    AgentRunStatus.REJECTED: frozenset(),
    AgentRunStatus.CANCELLED: frozenset(),
    AgentRunStatus.FAILED: frozenset(),
    AgentRunStatus.PROVIDER_OUTCOME_UNKNOWN: frozenset(),
}


_STEP_TRANSITIONS: Mapping[AgentStepStatus, frozenset[AgentStepStatus]] = {
    AgentStepStatus.PENDING: frozenset(
        {
            AgentStepStatus.RUNNING,
            AgentStepStatus.CANCELLED,
        }
    ),
    AgentStepStatus.RUNNING: frozenset(
        {
            AgentStepStatus.AWAITING_ACTION_CONFIRMATION,
            AgentStepStatus.SUCCEEDED,
            AgentStepStatus.FAILED,
            AgentStepStatus.CANCELLED,
            AgentStepStatus.COMPENSATION_REQUIRED,
            AgentStepStatus.PROVIDER_OUTCOME_UNKNOWN,
        }
    ),
    AgentStepStatus.AWAITING_ACTION_CONFIRMATION: frozenset(
        {
            AgentStepStatus.PENDING,
            AgentStepStatus.REJECTED,
            AgentStepStatus.CANCELLED,
        }
    ),
    AgentStepStatus.COMPENSATION_REQUIRED: frozenset(
        {
            AgentStepStatus.PENDING,
            AgentStepStatus.FAILED,
        }
    ),
    AgentStepStatus.SUCCEEDED: frozenset(),
    AgentStepStatus.REJECTED: frozenset(),
    AgentStepStatus.CANCELLED: frozenset(),
    AgentStepStatus.FAILED: frozenset(),
    AgentStepStatus.PROVIDER_OUTCOME_UNKNOWN: frozenset(),
}


def _transition[
    StatusT: StrEnum
](
    current: StatusT,
    target: StatusT,
    transitions: Mapping[StatusT, frozenset[StatusT]],
) -> StatusT:
    if target not in transitions[current]:
        raise InvalidAgentTransition(
            f"transition from {current.value} to {target.value} is not allowed"
        )
    return target


def transition_run(
    current: AgentRunStatus,
    target: AgentRunStatus,
) -> AgentRunStatus:
    return _transition(current, target, _RUN_TRANSITIONS)


def transition_step(
    current: AgentStepStatus,
    target: AgentStepStatus,
) -> AgentStepStatus:
    return _transition(current, target, _STEP_TRANSITIONS)


def approval_is_current(
    *,
    approved_fingerprint: str,
    current_fingerprint: str,
    approved_tool_catalog_version: str,
    current_tool_catalog_version: str,
) -> bool:
    return (
        approved_fingerprint == current_fingerprint
        and approved_tool_catalog_version == current_tool_catalog_version
    )
