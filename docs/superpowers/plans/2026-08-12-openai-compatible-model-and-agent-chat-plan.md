# 通用模型接入与运营智能体对话界面实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让管理员安全接入自备 OpenAI 兼容文本模型，并把现有运营智能体升级为可持久化、可恢复、仍受计划批准与风险门禁控制的对话式工作台。

**Architecture:** 在现有模块化单体中新增受 SSRF 防护的 `openai_compatible` 文本 Provider，并继续复用 `ModelConfig`、Adapter Factory 和模型用量治理。运营智能体新增成员私有的聊天会话/消息投影与严格结构化意图编排；真正执行仍调用现有 `PlanService`、`AgentExecutor`、Celery 状态机和确认 API。

**Tech Stack:** FastAPI、SQLAlchemy 2、Alembic、Pydantic v2、httpx、PostgreSQL、Redis、Next.js/React、TypeScript、Vitest/Testing Library、Playwright、Docker Compose。

## Global Constraints

- 通用接入第一版只支持 OpenAI Chat Completions 与 Models 合同下的文本能力。
- 生产环境只允许 HTTPS；开发环境只额外允许本机 loopback HTTP。
- API Key、完整自定义端点、Prompt、聊天正文和供应商原始错误不得进入普通日志、公开读取响应和轻量备份。
- 自定义 Provider 的价格由供应商管理；系统只限制并发、RPM、请求和 token，不伪造人民币费用。
- 聊天记录是交互记录，不是执行真相；计划、运行、步骤、确认、产物和风险记录仍为服务端权威。
- Viewer 只读；Editor/Admin 按现有权限操作；Demo 只使用 Mock；跨工作区或跨成员返回 404。
- 不新增 LangGraph、通用 MCP、Shell、任意 URL 工具、自动发布或永久删除能力。
- 不修改已提交的历史迁移；新迁移从 `20260812_0038` 顺序前进。
- 必须 TDD：每个生产行为先看到对应测试因缺失功能正确失败，再写最小实现。

---

### Task 1: 通用文本 Provider 配置合同与迁移

**Files:**
- Create: `apps/api/migrations/versions/20260812_0039_openai_compatible_config.py`
- Modify: `apps/api/app/modules/models/models.py`
- Modify: `apps/api/app/modules/models/config_service.py`
- Modify: `apps/api/app/modules/models/router.py`
- Modify: `apps/api/tests/models/test_qianwen_config.py`
- Create: `apps/api/tests/models/test_openai_compatible_config.py`
- Modify: `apps/api/tests/workspace/test_migrations.py`
- Modify: `apps/api/tests/schema/test_schema_consistency.py`

**Interfaces:**
- Produces: `provider="openai_compatible"` 配置、私有 `endpoint_base_url`、公开 `endpoint_host`、`ModelConfigService.save_openai_compatible(...)`。
- Consumes: 现有 `ModelConfig` 加密密钥、工作区权限、配置版本与公开读取合同。

- [ ] **Step 1: 写配置隔离和密钥/端点隐藏的失败测试**

```python
def test_admin_saves_openai_compatible_text_config_without_reading_secrets(client, admin_headers):
    response = client.post(
        f"/v1/workspaces/{workspace_id}/model-configs",
        headers=admin_headers,
        json={
            "provider": "openai_compatible",
            "display_name": "我的文本模型",
            "model_id": "example-chat",
            "base_url": "https://api.example.com/v1",
            "capabilities": ["text"],
            "status": "community",
            "api_key": "test-only-secret",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["provider"] == "openai_compatible"
    assert body["endpoint_host"] == "api.example.com"
    assert "base_url" not in body
    assert "api_key" not in body
    assert "encrypted_api_key" not in body
```

同时覆盖 Admin/Editor/Viewer、跨工作区 404、只允许 `text`、配置名称和模型 ID 长度、空密钥更新保留旧密钥，以及轻量备份不包含端点或密钥。

- [ ] **Step 2: 运行 RED**

Run: `cd apps/api && .venv/bin/python -m pytest tests/models/test_openai_compatible_config.py tests/models/test_qianwen_config.py -q`

Expected: 请求 Schema 拒绝 `display_name/base_url` 或 `openai_compatible` 不在配置服务中。

- [ ] **Step 3: 新增 0039 迁移和 ORM 字段**

`model_configs` 新增：

```python
display_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
endpoint_base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
```

数据库约束要求 `openai_compatible` 同时具有 `display_name` 和 `endpoint_base_url`，且 capability 由服务层固定为 `text`。现有 Qianwen 行保持可读。

- [ ] **Step 4: 扩展严格写入与公开读取合同**

`ModelConfigCreate` 增加可选 `display_name`、`base_url`；服务层按照 Provider 分支验证：Qianwen 拒绝它们，自定义 Provider 拒绝 region/workspace ID，固定 `AdapterStatus.COMMUNITY` 和 `{Capability.TEXT}`。`ModelConfigRead` 只返回 `display_name` 和解析后的 `endpoint_host`。

- [ ] **Step 5: 运行 GREEN、迁移和 Schema 检查**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/models/test_openai_compatible_config.py tests/models/test_qianwen_config.py tests/workspace/test_migrations.py tests/schema/test_schema_consistency.py -q
```

Expected: 全部通过，迁移 head 为 `20260812_0039`。

- [ ] **Step 6: 提交**

```bash
git add apps/api/migrations/versions/20260812_0039_openai_compatible_config.py apps/api/app/modules/models apps/api/tests/models apps/api/tests/workspace/test_migrations.py apps/api/tests/schema/test_schema_consistency.py
git commit -m "feat: store generic text model configurations"
```

### Task 2: 自定义端点 SSRF 防护与无生成连接测试

**Files:**
- Create: `apps/api/app/modules/models/openai_compatible_endpoint.py`
- Create: `apps/api/app/modules/models/openai_compatible_connection.py`
- Modify: `apps/api/app/modules/models/router.py`
- Create: `apps/api/tests/models/test_openai_compatible_endpoint.py`
- Create: `apps/api/tests/models/test_openai_compatible_connection.py`

**Interfaces:**
- Produces: `normalize_openai_base_url(value, app_env) -> NormalizedProviderEndpoint`、`probe_openai_compatible_connection(...) -> str | None`。
- Consumes: Task 1 的私有 base URL、公开 model ID 和加密 API Key。

- [ ] **Step 1: 写 URL 与连接探针失败测试**

覆盖 HTTPS 成功、开发 localhost、生产 HTTP 拒绝、credentials/query/fragment/反斜杠/双重编码拒绝、DNS 私网/回环/元数据地址拒绝、重定向拒绝、peer IP 不一致拒绝、超时、401、模型缺失和非法 Models JSON。

```python
def test_connection_probe_accepts_only_configured_model():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"object": "list", "data": [{"id": "expected-model", "object": "model"}]},
            request=request,
        )
    )
    assert probe_openai_compatible_connection(
        api_key="test-key",
        base_url="https://api.example.com/v1",
        model_id="expected-model",
        transport=transport,
        resolver=lambda host: ["203.0.113.10"],
        peer_ip="203.0.113.10",
    ) is None
```

- [ ] **Step 2: 运行 RED**

Run: `cd apps/api && .venv/bin/python -m pytest tests/models/test_openai_compatible_endpoint.py tests/models/test_openai_compatible_connection.py -q`

Expected: 模块不存在。

- [ ] **Step 3: 实现端点规范化和 DNS/peer 双重校验**

固定拼接 `${base_url}/models` 与 `${base_url}/chat/completions`，`follow_redirects=False`、`trust_env=False`。解析使用 `ipaddress.ip_address`，拒绝 `is_private/is_loopback/is_link_local/is_multicast/is_reserved/is_unspecified`；只在 `app_env=development` 时对显式 loopback host 放行。

- [ ] **Step 4: 实现 Models 探针和稳定错误码**

返回值仅允许：`None`、`MODEL_AUTHENTICATION_FAILED`、`MODEL_TIMEOUT`、`MODEL_PROVIDER_UNAVAILABLE`、`MODEL_NOT_FOUND`、`MODEL_INVALID_RESPONSE`、`MODEL_ENDPOINT_UNSAFE`。不得包含响应正文或目标 URL。

- [ ] **Step 5: 接入既有验证 API 并运行 GREEN**

`ControlledValidationService` 根据 Provider 选择千问或通用探针；连接测试不创建模型生成 attempt。运行上述专项测试和既有千问连接测试。

- [ ] **Step 6: 提交**

```bash
git add apps/api/app/modules/models apps/api/tests/models
git commit -m "feat: validate generic provider endpoints safely"
```

### Task 3: 通用结构化文本 Adapter 与未知价格用量治理

**Files:**
- Create: `apps/api/app/modules/models/adapters/openai_compatible.py`
- Create: `apps/api/migrations/versions/20260812_0040_openai_compatible_usage.py`
- Modify: `apps/api/app/modules/models/adapter_factory.py`
- Modify: `apps/api/app/modules/models/usage.py`
- Modify: `apps/api/app/modules/models/models.py`
- Create: `apps/api/tests/models/test_openai_compatible_adapter.py`
- Create: `apps/api/tests/models/test_openai_compatible_business_selection.py`
- Modify: `apps/api/tests/models/test_usage_governance.py`

**Interfaces:**
- Produces: `OpenAICompatibleTextProvider.generate_structured(ModelRequest[T]) -> T`；Factory 可选择 Qianwen 或自定义文本配置。
- Consumes: Task 2 安全 endpoint、现有 `ModelRequest`、`AttemptGovernor` 与严格 Pydantic 输出。

- [ ] **Step 1: 写 Adapter 和治理 RED 测试**

覆盖严格 JSON、拒绝 Markdown/多余字段/类型猜测/截断、禁用重定向、401 不重试、429/5xx 最多重试一次、安全日志、配置版本固定、跨工作区隔离、无配置 409、不回退 Mock。

```python
class Reply(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reply: str

result = await provider.generate_structured(ModelRequest(
    capability=Capability.TEXT,
    prompt="reply safely",
    response_model=Reply,
    inputs={"message": "你好"},
))
assert result.reply == "你好"
```

用量测试证明自定义 Provider 记录 token 与 `pricing_version=provider-managed-unknown`，费用字段为不可用语义而非伪造人民币估算，同时仍执行并发/RPM/请求/token 限制。

- [ ] **Step 2: 运行 RED**

Run: `cd apps/api && .venv/bin/python -m pytest tests/models/test_openai_compatible_adapter.py tests/models/test_openai_compatible_business_selection.py tests/models/test_usage_governance.py -q`

Expected: Adapter 缺失或 Factory 拒绝 Provider。

- [ ] **Step 3: 实现最小 OpenAI Chat Completions Adapter**

请求只包含 `model/messages/response_format/stream`，不发送千问私有字段。响应读取 `choices[0].message.content`，只做一次 `json.loads` 和 strict Pydantic 校验。

- [ ] **Step 4: 扩展 Factory 与用量账本**

Factory 读取 Task 1 配置并在调用边界解密密钥。新增 0040 迁移为 reservation/attempt 增加 `cost_known`；未知价格使用独立 pricing mode，数据库 attempt 明确记录 `cost_known=False`，而不是把 `0` 展示为免费。每日 cost policy 对自定义 Provider 标记不适用，其他政策继续强制。

- [ ] **Step 5: 运行 GREEN 与业务回归**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/models tests/analysis tests/generation tests/risk_rag -q
```

Expected: 通用 Provider 专项与既有千问/Mock 业务回归全部通过。

- [ ] **Step 6: 提交**

```bash
git add apps/api/app/modules/models apps/api/migrations/versions/20260812_0040_openai_compatible_usage.py apps/api/tests/models
git commit -m "feat: call governed openai compatible text models"
```

### Task 4: 模型设置页面双入口与连接状态

**Files:**
- Modify: `apps/web/src/components/models/model-config-form.tsx`
- Modify: `apps/web/src/components/models/model-config-form.test.tsx`
- Modify: `apps/web/src/components/models/model-status.tsx`
- Modify: `apps/web/src/lib/model-api.ts`
- Modify: `packages/shared-schemas/openapi.json`
- Modify: `packages/shared-schemas/src/schema.ts`
- Modify: `docs/open-source/qianwen-model-configuration.md`
- Create: `docs/open-source/openai-compatible-model-configuration.md`

**Interfaces:**
- Produces: `千问官方 | OpenAI 兼容` 配置切换、脱敏端点状态和“测试连接”操作。
- Consumes: Tasks 1–3 API、生成 TypeScript Schema、现有易懂/专业模式。

- [ ] **Step 1: 写 UI RED 测试**

证明 Admin 可选 Provider、填写名称/URL/模型/Key、保存后 Key 清空、连接测试展示成功/错误；Viewer 看不到密钥和端点表单；易懂模式不出现 `base_url/provider` 等开发术语；费用区域显示“费用由供应商结算”。

- [ ] **Step 2: 运行 RED**

Run: `cd apps/web && pnpm test -- src/components/models/model-config-form.test.tsx`

Expected: 页面没有 Provider 切换和通用字段。

- [ ] **Step 3: 实现双入口和安全状态**

千问表单行为保持不变；OpenAI 兼容表单使用“服务地址”“模型名称”“模型服务密钥”等运营文案。连接按钮保存成功后才启用，pending 时禁止重复提交。

- [ ] **Step 4: 重新生成 OpenAPI 类型并运行 GREEN**

Run:

```bash
cd apps/api && .venv/bin/python scripts/export_openapi.py
cd ../web && pnpm test -- src/components/models/model-config-form.test.tsx && pnpm typecheck
```

- [ ] **Step 5: 提交**

```bash
git add apps/web/src/components/models apps/web/src/lib/model-api.ts packages/shared-schemas docs/open-source
git commit -m "feat: configure compatible text providers in workbench"
```

### Task 5: 聊天会话持久化、隔离 API 与完整备份

**Files:**
- Create: `apps/api/migrations/versions/20260812_0041_agent_chats.py`
- Modify: `apps/api/app/modules/operations_agent/models.py`
- Modify: `apps/api/app/modules/operations_agent/schemas.py`
- Create: `apps/api/app/modules/operations_agent/chat_service.py`
- Modify: `apps/api/app/modules/operations_agent/router.py`
- Modify: `apps/api/app/modules/exports/manifest.py`
- Modify: `apps/api/app/modules/exports/json_backup.py`
- Modify: `apps/api/app/modules/exports/restore_preview.py`
- Create: `apps/api/tests/operations_agent/test_chat_service.py`
- Create: `apps/api/tests/operations_agent/test_chat_router.py`
- Modify: `apps/api/tests/exports/test_full_backup.py`
- Modify: `apps/api/tests/workspace/test_migrations.py`
- Modify: `apps/api/tests/schema/test_schema_consistency.py`

**Interfaces:**
- Produces: `AgentChatSession`、`AgentChatMessage`、`AgentChatService.create/list/read/append/archive` 与 `/agent/chats` API。
- Consumes: 工作区会话鉴权、成员 ID、现有 plan/run 外键和 ZIP 恢复映射。

- [ ] **Step 1: 写会话/消息 RED 测试**

覆盖成员私有、跨 workspace 404、其他成员 404、Viewer 只读、CSRF、幂等冲突、稳定顺序、分页、4,000 字限制、归档后不可继续写、标题确定性生成、重启后读取相同记录。

```python
chat = service.create(idempotency_key="chat-1")
message = service.append_user_message(
    chat.id,
    content="帮我分析这个账号最近表现",
    idempotency_key="message-1",
)
assert service.read(chat.id).messages[0].id == message.id
assert service.read(chat.id).title == "帮我分析这个账号最近表现"
```

- [ ] **Step 2: 运行 RED**

Run: `cd apps/api && .venv/bin/python -m pytest tests/operations_agent/test_chat_service.py tests/operations_agent/test_chat_router.py -q`

Expected: 新模型/服务/API 缺失。

- [ ] **Step 3: 新增 0041 和追加式消息服务**

会话使用 `active|archived`；消息角色使用 `user|assistant|system_event`，类型使用 `text|plan|run|confirmation|artifact|safe_error`。唯一约束为 `(workspace_id, session_id, sequence_no)` 和 `(workspace_id, idempotency_key)`。消息正文不得写入事件日志。

- [ ] **Step 4: 实现 API 与备份边界**

列表/详情使用有界分页；完整 ZIP 的结构化数据包含会话/消息，轻量 JSON 只保留会话数量与安全元数据，不包含聊天正文。恢复时重新映射 workspace/member/plan/run IDs，失败整体回滚。

- [ ] **Step 5: 运行 GREEN、迁移和备份回归**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/operations_agent/test_chat_service.py tests/operations_agent/test_chat_router.py tests/exports/test_full_backup.py tests/workspace/test_migrations.py tests/schema/test_schema_consistency.py -q
```

Expected: head 为 `20260812_0041`，隔离与恢复测试通过。

- [ ] **Step 6: 提交**

```bash
git add apps/api/migrations/versions/20260812_0041_agent_chats.py apps/api/app/modules/operations_agent apps/api/app/modules/exports apps/api/tests
git commit -m "feat: persist private operations agent chats"
```

### Task 6: 严格对话意图编排与现有计划衔接

**Files:**
- Create: `apps/api/app/modules/operations_agent/chat_turn.py`
- Modify: `apps/api/app/modules/operations_agent/chat_service.py`
- Modify: `apps/api/app/modules/operations_agent/schemas.py`
- Modify: `apps/api/app/modules/operations_agent/router.py`
- Modify: `apps/api/app/modules/models/adapter_factory.py`
- Create: `apps/api/tests/operations_agent/test_chat_turn.py`
- Modify: `apps/api/tests/operations_agent/test_planning.py`

**Interfaces:**
- Produces: `AgentChatTurnService.send(...) -> AgentChatRead`、严格 `AgentChatIntent`。
- Consumes: Task 3 文本 Adapter、Task 5 会话、现有 Briefing/PlanService 和模型用量治理。

- [ ] **Step 1: 写意图、失败和计划衔接 RED 测试**

覆盖 greeting 不建计划、缺账号 clarify、明确目标 create_plan、模型输出任意 tool/URL/额外字段被拒、上下文最多 12 条/12,000 字、模型失败后用户消息仍在并追加安全错误、不回退 Mock、相同幂等键不重复调用。

```python
class AgentChatIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    intent: Literal["greeting", "clarify", "create_plan", "explain_state"]
    reply: str = Field(min_length=1, max_length=1000)
    objective: str | None = Field(default=None, max_length=1000)
    needs_account: bool
```

- [ ] **Step 2: 运行 RED**

Run: `cd apps/api && .venv/bin/python -m pytest tests/operations_agent/test_chat_turn.py -q`

Expected: 编排服务缺失。

- [ ] **Step 3: 实现固定 Prompt、严格 Schema 和有界上下文**

模型只负责意图与自然回复。服务端忽略模型对工具、权限、账号或状态的任何声明；账号来自已验证会话范围。`create_plan` 必须调用现有 `PlanService.create`，并追加引用真实 `plan_id` 的计划事件消息。

- [ ] **Step 4: 实现安全错误与幂等语义**

配置缺失、政策缺失、额度不足、鉴权、超时、无效输出分别映射稳定中文消息。供应商可能计费的未知结果不能自动重试；同一幂等键返回原 turn。

- [ ] **Step 5: 运行 GREEN 与 Agent 回归**

Run: `cd apps/api && .venv/bin/python -m pytest tests/operations_agent tests/models/test_openai_compatible_business_selection.py -q`

- [ ] **Step 6: 提交**

```bash
git add apps/api/app/modules/operations_agent apps/api/tests/operations_agent
git commit -m "feat: orchestrate governed agent chat turns"
```

### Task 7: Codex 风格聊天工作台

**Files:**
- Create: `apps/web/src/components/agent/chat-sidebar.tsx`
- Create: `apps/web/src/components/agent/chat-message-list.tsx`
- Create: `apps/web/src/components/agent/chat-composer.tsx`
- Create: `apps/web/src/components/agent/agent-chat-workspace.tsx`
- Modify: `apps/web/src/components/agent/agent-workspace-page.tsx`
- Modify: `apps/web/src/lib/agent-api.ts`
- Create: `apps/web/src/components/agent/agent-chat-workspace.test.tsx`
- Modify: `apps/web/src/components/agent/agent-workspace.test.tsx`
- Modify: `packages/shared-schemas/openapi.json`
- Modify: `packages/shared-schemas/src/schema.ts`

**Interfaces:**
- Produces: 会话侧栏、消息流、输入框、计划/运行/确认/结果卡的对话式页面。
- Consumes: Tasks 5–6 Chat API 和现有计划批准、运行、确认 API。

- [ ] **Step 1: 写 UI RED 测试**

覆盖空状态示例、新建会话、历史切换、发送“你好”、pending 禁止重复发送、计划卡批准、运行状态恢复、归档、Viewer 只读、错误重试、390px 抽屉与键盘焦点。

```tsx
expect(screen.getByRole("textbox", { name: "给运营智能体发消息" })).toBeVisible();
await user.type(screen.getByRole("textbox"), "你好");
await user.click(screen.getByRole("button", { name: "发送" }));
expect(await screen.findByText("你好，我可以帮你分析账号运营问题。"))
  .toBeVisible();
```

- [ ] **Step 2: 运行 RED**

Run: `cd apps/web && pnpm test -- src/components/agent/agent-chat-workspace.test.tsx`

Expected: 新聊天组件不存在。

- [ ] **Step 3: 实现桌面/移动聊天布局**

桌面左栏 280px、中间自适应；移动端历史为 modal drawer。输入框始终显示当前平台/账号范围和“外部 API 可能产生费用”。消息中的计划、运行和确认卡复用现有组件和 API，不复制状态计算。

- [ ] **Step 4: 实现刷新恢复和无障碍**

选中 chat ID 使用 URL `?chat=`，前进/后退可恢复；非法 chat 回到最近会话。消息列表使用 `aria-live=polite`，发送支持 `Cmd/Ctrl+Enter`，焦点在发送后回到输入框。

- [ ] **Step 5: 重新生成类型并运行 GREEN**

Run:

```bash
cd apps/api && .venv/bin/python scripts/export_openapi.py
cd ../web
pnpm test -- src/components/agent
pnpm lint
pnpm typecheck
pnpm build
```

- [ ] **Step 6: 提交**

```bash
git add apps/web/src/components/agent apps/web/src/lib/agent-api.ts packages/shared-schemas
git commit -m "feat: deliver conversational operations agent workspace"
```

### Task 8: 全闭环 E2E、部署文档与本地持久化验收

**Files:**
- Create: `tests/e2e/openai-compatible-model.spec.ts`
- Create: `tests/e2e/agent-chat.spec.ts`
- Modify: `tests/e2e/playwright.config.ts`
- Modify: `infra/docker/compose.yml`
- Modify: `docs/architecture/model-adapters.md`
- Modify: `docs/acceptance/requirements-traceability.md`
- Create: `docs/acceptance/evidence/generic-model-agent-chat-2026-08-12.md`

**Interfaces:**
- Produces: 可重复的 Mock Provider E2E、真实本地重启持久化证据和更新后的追溯矩阵。
- Consumes: Tasks 1–7 完整功能。

- [ ] **Step 1: 写端到端 RED 用例**

E2E 启动隔离 OpenAI 兼容 Mock 服务，覆盖 `/models`、结构化 chat completions、错误码和 token usage。完整流程：Admin 配置 → 测试连接 → 创建聊天 → 发送“你好” → 收到回复 → 发送明确目标 → 计划卡 → 批准运行 → 查看结果 → 重启 Compose → 恢复相同 chat/message/plan/run IDs。

- [ ] **Step 2: 运行 RED**

Run: `pnpm exec playwright test tests/e2e/openai-compatible-model.spec.ts tests/e2e/agent-chat.spec.ts`

Expected: 路由或 UI 元素缺失。

- [ ] **Step 3: 补齐隔离 Mock Provider 与文档**

Mock 只监听 Compose 内部网络，不使用真实 Key、外网或费用。文档明确通用兼容范围、SSRF 边界、未知价格、聊天隐私和人工发布边界。

- [ ] **Step 4: 运行完整验证**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest -q
cd ../web && pnpm test && pnpm lint && pnpm typecheck && pnpm build
cd ../../packages/extension && pnpm test && pnpm lint && pnpm typecheck && pnpm build
cd ../..
bash scripts/check_openapi_drift.sh
bash scripts/check_metric_type_drift.sh
bash scripts/secret-scan.sh
bash scripts/verify-fresh-install.sh
```

Expected: 所有命令 exit 0；临时 schema、容器、网络和卷自动清理；原持久化开发数据库不变。

- [ ] **Step 5: 在保留数据的本地实例执行迁移与重启验收**

先备份并只运行 `migrate`，确认 head `20260812_0041`；重建 API/Web/Worker，不删除卷。用合成消息完成一次聊天并正常停止/重启，验证聊天、计划和运行 ID 不变。不得在未再次明确授权时调用真实供应商。

- [ ] **Step 6: 最终代码复核与提交**

检查设计验收 10 条逐项有证据，确认 Critical/Important 为 0，再提交：

```bash
git add tests/e2e infra/docker/compose.yml docs
git commit -m "test: accept generic models and agent chat"
```

实施完成后暂停；不自动 push、不发布 GitHub Release、不删除用户 Docker 卷，也不运行新的真实计费调用。
