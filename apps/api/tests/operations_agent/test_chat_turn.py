from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.generation import models as generation_models  # noqa: F401
from app.modules.operations_agent.chat_turn import (
    AgentChatIntent,
    AgentChatTurnService,
    DeterministicChatIntentProvider,
)
from tests.operations_agent.test_chat_service import _environment, _service


def _context(workspace_id, member_id) -> WorkspaceContext:
    return WorkspaceContext(
        workspace_id=workspace_id,
        member_id=member_id,
        role="editor",
    )


@dataclass
class StubIntentProvider:
    intent: AgentChatIntent | None = None
    error: Exception | None = None
    calls: int = 0

    async def classify(
        self,
        *,
        history: tuple[dict[str, str], ...],
        message: str,
    ) -> AgentChatIntent:
        self.calls += 1
        assert len(history) <= 12
        assert sum(len(item["content"]) for item in history) <= 12_000
        if self.error is not None:
            raise self.error
        assert self.intent is not None
        return self.intent


@dataclass
class TransactionCheckingProvider:
    session: Session

    async def classify(
        self,
        *,
        history: tuple[dict[str, str], ...],
        message: str,
    ) -> AgentChatIntent:
        del history, message
        assert not self.session.in_transaction()
        return AgentChatIntent(
            intent="greeting",
            reply="你好，我可以帮你分析账号运营问题。",
            objective=None,
            needs_account=False,
        )


def test_greeting_is_persisted_as_a_normal_assistant_reply() -> None:
    session, workspace, first, _ = _environment()
    chat_service = _service(session, workspace, first)
    chat = chat_service.create(idempotency_key="turn-greeting-chat")
    provider = StubIntentProvider(
        AgentChatIntent(
            intent="greeting",
            reply="你好，我可以帮你分析账号运营问题。",
            objective=None,
            needs_account=False,
        )
    )
    service = AgentChatTurnService(
        session, _context(workspace.id, first.id), intent_provider=provider
    )

    detail = asyncio.run(
        service.send(
            chat.id,
            content="你好",
            idempotency_key="turn-greeting",
        )
    )

    assert [message.role.value for message in detail.messages] == [
        "user",
        "assistant",
    ]
    assert detail.messages[-1].content == "你好，我可以帮你分析账号运营问题。"
    assert detail.messages[-1].kind.value == "text"


def test_turn_is_idempotent_and_does_not_call_provider_twice() -> None:
    session, workspace, first, _ = _environment()
    chat_service = _service(session, workspace, first)
    chat = chat_service.create(idempotency_key="turn-repeat-chat")
    provider = StubIntentProvider(
        AgentChatIntent(
            intent="clarify",
            reply="请先告诉我你想查看哪个平台账号。",
            objective=None,
            needs_account=True,
        )
    )
    service = AgentChatTurnService(
        session, _context(workspace.id, first.id), intent_provider=provider
    )

    first_result = asyncio.run(
        service.send(
            chat.id,
            content="帮我分析",
            idempotency_key="turn-repeat",
        )
    )
    second_result = asyncio.run(
        service.send(
            chat.id,
            content="帮我分析",
            idempotency_key="turn-repeat",
        )
    )

    assert provider.calls == 1
    assert [item.id for item in first_result.messages] == [
        item.id for item in second_result.messages
    ]


def test_turn_idempotency_key_cannot_be_reused_with_different_content() -> None:
    session, workspace, first, _ = _environment()
    chat_service = _service(session, workspace, first)
    chat = chat_service.create(idempotency_key="turn-conflict-chat")
    service = AgentChatTurnService(
        session,
        _context(workspace.id, first.id),
        intent_provider=StubIntentProvider(
            AgentChatIntent(
                intent="greeting",
                reply="你好",
                objective=None,
                needs_account=False,
            )
        ),
    )
    asyncio.run(
        service.send(
            chat.id,
            content="你好",
            idempotency_key="turn-conflict",
        )
    )

    with pytest.raises(ValueError, match="idempotency"):
        asyncio.run(
            service.send(
                chat.id,
                content="不同内容",
                idempotency_key="turn-conflict",
            )
        )


def test_provider_failure_keeps_user_message_and_adds_safe_error() -> None:
    session, workspace, first, _ = _environment()
    chat_service = _service(session, workspace, first)
    chat = chat_service.create(idempotency_key="turn-error-chat")
    service = AgentChatTurnService(
        session,
        _context(workspace.id, first.id),
        intent_provider=StubIntentProvider(error=TimeoutError("private detail")),
    )

    detail = asyncio.run(
        service.send(
            chat.id,
            content="帮我看看最近的问题",
            idempotency_key="turn-error",
        )
    )

    assert [item.kind.value for item in detail.messages] == [
        "text",
        "safe_error",
    ]
    assert "private detail" not in detail.messages[-1].content
    assert "暂时没有回复" in detail.messages[-1].content


def test_user_message_commits_before_external_provider_is_called() -> None:
    session, workspace, first, _ = _environment()
    chat_service = _service(session, workspace, first)
    chat = chat_service.create(idempotency_key="turn-transaction-chat")
    service = AgentChatTurnService(
        session,
        _context(workspace.id, first.id),
        intent_provider=TransactionCheckingProvider(session),
    )

    detail = asyncio.run(
        service.send(
            chat.id,
            content="你好",
            idempotency_key="turn-transaction",
        )
    )

    assert [item.role.value for item in detail.messages] == [
        "user",
        "assistant",
    ]


def test_create_plan_without_verified_scope_is_downgraded_to_clarify() -> None:
    session, workspace, first, _ = _environment()
    chat_service = _service(session, workspace, first)
    chat = chat_service.create(idempotency_key="turn-scope-chat")
    service = AgentChatTurnService(
        session,
        _context(workspace.id, first.id),
        intent_provider=StubIntentProvider(
            AgentChatIntent(
                intent="create_plan",
                reply="我来生成计划。",
                objective="分析最近内容表现",
                needs_account=False,
            )
        ),
    )

    detail = asyncio.run(
        service.send(
            chat.id,
            content="分析最近内容表现",
            idempotency_key="turn-no-scope",
        )
    )

    assert detail.messages[-1].kind.value == "text"
    assert detail.messages[-1].plan_id is None
    assert "选择" in detail.messages[-1].content


def test_deterministic_chat_recognizes_hotspot_research_intent() -> None:
    intent = asyncio.run(
        DeterministicChatIntentProvider().classify(
            history=(),
            message="用最新热榜给我生成三个选题",
        )
    )

    assert intent.intent == "research_hotspot"
    assert intent.needs_account is True


def test_hotspot_chat_requires_an_explicit_account_scope() -> None:
    session, workspace, first, _ = _environment()
    chat_service = _service(session, workspace, first)
    chat = chat_service.create(idempotency_key="turn-hotspot-chat")
    service = AgentChatTurnService(
        session,
        _context(workspace.id, first.id),
        intent_provider=StubIntentProvider(
            AgentChatIntent(
                intent="research_hotspot",
                reply="开始核实热点。",
                objective="根据热点生成选题",
                needs_account=True,
            )
        ),
    )

    detail = asyncio.run(
        service.send(
            chat.id,
            content="根据热点生成选题",
            idempotency_key="turn-hotspot-no-scope",
        )
    )

    assert detail.messages[-1].kind.value == "text"
    assert "选择一个平台账号" in detail.messages[-1].content
