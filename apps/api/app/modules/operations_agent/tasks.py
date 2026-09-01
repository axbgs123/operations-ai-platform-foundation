from uuid import UUID

from celery import shared_task  # type: ignore[import-untyped]

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.modules.operations_agent.executor import (
    AgentClaimLost,
    AgentClaimUnavailable,
    AgentExecutionInvalidated,
    AgentExecutor,
    AgentRecovery,
)
from app.modules.operations_agent.domain_tools import DomainToolRunner
from app.modules.operations_agent.models import AgentRunStatus
from app.modules.operations_agent.planning import build_planning_registry


def _executor() -> AgentExecutor:
    registry = build_planning_registry()
    return AgentExecutor(
        SessionFactory,
        registry=registry,
        tool_runner=DomainToolRunner(
            SessionFactory,
            registry=registry,
        ),
    )


def _recovery() -> AgentRecovery:
    return AgentRecovery(
        SessionFactory,
        registry=build_planning_registry(),
    )


@shared_task(name="operations_agent.execute_run")
def execute_run(run_id: str) -> dict[str, str]:
    executor = _executor()
    try:
        claim = executor.claim_next_step(UUID(run_id))
    except AgentClaimUnavailable:
        return {"run_id": run_id, "status": "not_claimable"}
    except AgentExecutionInvalidated:
        executor.fail_invalidated(UUID(run_id))
        return {"run_id": run_id, "status": "execution_context_changed"}
    except AgentClaimLost:
        return {"run_id": run_id, "status": "claim_lost"}
    try:
        result = executor.execute_claim(claim)
    except AgentExecutionInvalidated:
        executor.fail_invalidated(UUID(run_id), claim=claim)
        return {"run_id": run_id, "status": "execution_context_changed"}
    except AgentClaimLost:
        return {"run_id": run_id, "status": "claim_lost"}
    if result.run_status is AgentRunStatus.RUNNING:
        settings = get_settings()
        if getattr(settings, "run_tasks_inline", settings.app_mock_mode):
            return execute_run(run_id)
        execute_run.delay(run_id)
    return {
        "run_id": run_id,
        "status": result.run_status.value,
    }


@shared_task(name="operations_agent.recover_pending")
def recover_pending() -> dict[str, object]:
    recovered = _recovery().recover_expired()
    for run_id in recovered:
        execute_run.delay(str(run_id))
    return {
        "status": "completed",
        "recovered_run_ids": [str(run_id) for run_id in recovered],
    }
