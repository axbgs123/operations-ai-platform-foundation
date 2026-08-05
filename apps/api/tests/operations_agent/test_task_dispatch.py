from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.operations_agent.models import AgentRunStatus


def test_router_executes_agent_run_inline_in_mock_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.operations_agent import router, tasks

    calls: list[tuple[str, str]] = []

    class FakeTask:
        def __call__(self, run_id: str) -> None:
            calls.append(("inline", run_id))

        def delay(self, run_id: str) -> None:
            calls.append(("delayed", run_id))

    monkeypatch.setattr(tasks, "execute_run", FakeTask())
    monkeypatch.setattr(
        router,
        "get_settings",
        lambda: SimpleNamespace(app_mock_mode=True),
        raising=False,
    )
    run_id = uuid4()

    router._enqueue_run(run_id)

    assert calls == [("inline", str(run_id))]


def test_mock_agent_run_continues_inline_without_broker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.operations_agent import tasks

    statuses = iter((AgentRunStatus.RUNNING, AgentRunStatus.SUCCEEDED))
    delayed: list[str] = []

    class FakeExecutor:
        def claim_next_step(self, _run_id):
            return object()

        def execute_claim(self, _claim):
            return SimpleNamespace(run_status=next(statuses))

    monkeypatch.setattr(tasks, "_executor", FakeExecutor)
    monkeypatch.setattr(
        tasks,
        "get_settings",
        lambda: SimpleNamespace(app_mock_mode=True),
        raising=False,
    )
    monkeypatch.setattr(
        tasks.execute_run,
        "delay",
        lambda run_id: delayed.append(run_id),
    )

    result = tasks.execute_run.run(str(uuid4()))

    assert result["status"] == "succeeded"
    assert delayed == []
