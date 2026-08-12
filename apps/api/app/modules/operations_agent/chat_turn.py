from __future__ import annotations

from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.content.account_models import Platform
from app.modules.models.capabilities import Capability, ModelRequest
from app.modules.models.adapter_factory import ModelSelectionError
from app.modules.models.adapters.qianwen import (
    ModelProviderError,
    safe_model_error_message,
)
from app.modules.models.config_service import ModelConfigurationRequired
from app.modules.operations_agent.chat_service import (
    AgentChatDetail,
    AgentChatService,
)
from app.modules.operations_agent.models import (
    AgentChatMessageKind,
    AgentChatRole,
)
from app.modules.operations_agent.planning import (
    AgentApprovalStale,
    InvalidAgentPlan,
    PlanService,
)
from app.modules.operations_agent.schemas import AgentPlanCreate


CHAT_INTENT_PROMPT = """你是运营工作台的意图分类器，只返回严格 JSON。
你只能判断用户是在问候、需要澄清、希望创建处理计划，还是解释当前状态。
你不能选择账号、调用工具、访问网址、批准计划或声称已经执行操作。
回复使用简洁中文，不承诺平台结果。"""


class AgentChatIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    intent: Literal["greeting", "clarify", "create_plan", "explain_state"]
    reply: str = Field(min_length=1, max_length=1000)
    objective: str | None = Field(default=None, max_length=1000)
    needs_account: bool


class ChatIntentProvider(Protocol):
    async def classify(
        self,
        *,
        history: tuple[dict[str, str], ...],
        message: str,
    ) -> AgentChatIntent: ...


class StructuredChatIntentProvider:
    def __init__(self, adapter: object) -> None:
        self._adapter = adapter

    async def classify(
        self,
        *,
        history: tuple[dict[str, str], ...],
        message: str,
    ) -> AgentChatIntent:
        generate = getattr(self._adapter, "generate_structured")
        result = await generate(
            ModelRequest(
                capability=Capability.TEXT,
                prompt=CHAT_INTENT_PROMPT,
                response_model=AgentChatIntent,
                inputs={"history": history, "message": message},
            )
        )
        if not isinstance(result, AgentChatIntent):
            raise ValueError("invalid chat intent response")
        return result


class DeterministicChatIntentProvider:
    async def classify(
        self,
        *,
        history: tuple[dict[str, str], ...],
        message: str,
    ) -> AgentChatIntent:
        del history
        normalized = message.strip().lower()
        if normalized in {"你好", "您好", "hi", "hello", "嗨"}:
            return AgentChatIntent(
                intent="greeting",
                reply=(
                    "你好，我可以帮你分析账号表现、查找运营问题，"
                    "也可以先生成一份可检查的处理计划。"
                ),
                objective=None,
                needs_account=False,
            )
        if any(
            word in normalized
            for word in ("分析", "优化", "生成", "诊断", "处理", "计划")
        ):
            return AgentChatIntent(
                intent="create_plan",
                reply="我可以先生成一份处理计划，确认后再执行。",
                objective=message.strip(),
                needs_account=True,
            )
        return AgentChatIntent(
            intent="clarify",
            reply="请告诉我你想查看哪个账号，以及希望解决什么运营问题。",
            objective=None,
            needs_account=True,
        )


class UnavailableChatIntentProvider:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def classify(
        self,
        *,
        history: tuple[dict[str, str], ...],
        message: str,
    ) -> AgentChatIntent:
        del history, message
        raise self._error


class AgentChatTurnService:
    def __init__(
        self,
        session: Session,
        context: WorkspaceContext,
        *,
        intent_provider: ChatIntentProvider,
    ) -> None:
        self._session = session
        self._context = context
        self._chats = AgentChatService(session, context)
        self._intent_provider = intent_provider

    async def send(
        self,
        chat_id: UUID,
        *,
        content: str,
        idempotency_key: str,
        account_id: UUID | None = None,
        platform: Platform | None = None,
    ) -> AgentChatDetail:
        key = idempotency_key.strip()
        if not key or len(key) > 160:
            raise ValueError("invalid turn idempotency key")
        user = self._chats.append_user_message(
            chat_id,
            content=content,
            idempotency_key=f"chat-turn:{key}:user",
        )
        assistant_key = f"chat-turn:{key}:assistant"
        existing_assistant = self._chats.message_by_key(assistant_key)
        if existing_assistant is not None:
            if existing_assistant.session_id != chat_id:
                raise ValueError("idempotency key conflict")
            return self._chats.read(chat_id)
        history = self._bounded_history(chat_id)
        try:
            intent = await self._intent_provider.classify(
                history=history,
                message=user.content,
            )
            self._append_intent_result(
                chat_id,
                intent=intent,
                assistant_key=assistant_key,
                account_id=account_id,
                platform=platform,
                turn_key=key,
            )
        except (
            ModelProviderError,
            ModelSelectionError,
            ModelConfigurationRequired,
            TimeoutError,
            ValueError,
        ) as error:
            self._chats.append_message(
                chat_id,
                content=self._safe_model_failure(error),
                idempotency_key=assistant_key,
                role=AgentChatRole.ASSISTANT,
                kind=AgentChatMessageKind.SAFE_ERROR,
            )
        return self._chats.read(chat_id)

    def _append_intent_result(
        self,
        chat_id: UUID,
        *,
        intent: AgentChatIntent,
        assistant_key: str,
        account_id: UUID | None,
        platform: Platform | None,
        turn_key: str,
    ) -> None:
        if intent.intent != "create_plan":
            self._chats.append_message(
                chat_id,
                content=intent.reply,
                idempotency_key=assistant_key,
                role=AgentChatRole.ASSISTANT,
                kind=AgentChatMessageKind.TEXT,
            )
            return
        if account_id is None or platform is None:
            self._chats.append_message(
                chat_id,
                content="请先选择一个平台账号，我再为这个账号生成处理计划。",
                idempotency_key=assistant_key,
                role=AgentChatRole.ASSISTANT,
                kind=AgentChatMessageKind.TEXT,
            )
            return
        objective = (intent.objective or "").strip()
        if not objective:
            self._chats.append_message(
                chat_id,
                content="请再具体说一下你希望解决的运营问题。",
                idempotency_key=assistant_key,
                role=AgentChatRole.ASSISTANT,
                kind=AgentChatMessageKind.TEXT,
            )
            return
        from app.modules.operations_agent.briefing import BriefingService

        briefing = BriefingService(self._session, self._context).generate()
        if (
            briefing.primary is None
            or briefing.primary.account_id != account_id
            or briefing.primary.platform is not platform
        ):
            self._chats.append_message(
                chat_id,
                content=(
                    "当前账号还没有可用于生成计划的优先事项。"
                    "你可以先导入数据并完成分析。"
                ),
                idempotency_key=assistant_key,
                role=AgentChatRole.ASSISTANT,
                kind=AgentChatMessageKind.TEXT,
            )
            return
        try:
            plan = PlanService(self._session, self._context).create(
                AgentPlanCreate(
                    objective=objective,
                    briefing_id=briefing.id,
                    platform=platform,
                    account_id=account_id,
                ),
                idempotency_key=f"chat-plan:{turn_key}",
            )
        except (AgentApprovalStale, InvalidAgentPlan, LookupError, ValueError):
            self._chats.append_message(
                chat_id,
                content=(
                    "账号数据状态刚刚发生了变化，暂时不能生成可靠计划。"
                    "请刷新数据后再试。"
                ),
                idempotency_key=assistant_key,
                role=AgentChatRole.ASSISTANT,
                kind=AgentChatMessageKind.SAFE_ERROR,
            )
            return
        self._chats.append_message(
            chat_id,
            content=(
                "我已经生成一份处理计划。请先检查步骤，"
                "批准后系统才会开始执行。"
            ),
            idempotency_key=assistant_key,
            role=AgentChatRole.ASSISTANT,
            kind=AgentChatMessageKind.PLAN,
            plan_id=plan.id,
        )

    def _bounded_history(
        self,
        chat_id: UUID,
    ) -> tuple[dict[str, str], ...]:
        messages = list(self._chats.read(chat_id, limit=200).messages[-12:])
        while (
            messages
            and sum(len(item.content) for item in messages) > 12_000
        ):
            messages.pop(0)
        return tuple(
            {"role": item.role.value, "content": item.content}
            for item in messages
        )

    @staticmethod
    def _safe_model_failure(error: Exception) -> str:
        if isinstance(error, ModelProviderError):
            return (
                f"{safe_model_error_message(error.code)}"
                "你的消息已经保存。"
            )
        if isinstance(error, (ModelConfigurationRequired, ModelSelectionError)):
            return "模型尚未正确配置。你的消息已经保存，请管理员检查模型设置。"
        return (
            "模型暂时没有回复。你的消息已经保存，"
            "请检查模型连接或稍后重试。"
        )
