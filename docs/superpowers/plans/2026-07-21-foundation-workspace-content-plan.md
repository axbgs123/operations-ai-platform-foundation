# Foundation、Workspace 与 Content Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 每项功能先写失败测试，再写最小实现。

**Goal:** 建立可复现的单仓库基础设施，完成公开体验区、独立成员邀请码、权限与审计、平台账号、栏目和单条内容的安全闭环。

**Architecture:** FastAPI 按 `workspace`、`content`、`jobs` 模块分层；SQLAlchemy 仓储统一注入工作区上下文；Next.js 仅通过生成的 API client 访问后端；公开体验区使用只读示例工作区和独立限额。

**Tech Stack:** Next.js 16、TypeScript、Vitest、Playwright；FastAPI、SQLAlchemy 2、Alembic、pytest；PostgreSQL 18/pgvector、Redis 8、S3 兼容存储、Docker Compose。

**Global Constraints:** 继承主计划全部约束。邀请码不等于共享密码：一人一码、一种角色、可撤销、服务端强哈希、首次填写显示名称后签发 HttpOnly 会话。

## Task 1: 初始化单仓库与可复现开发环境

**Files:**
- Create: `package.json`, `pnpm-workspace.yaml`, `.node-version`, `.gitignore`, `.env.example`
- Create: `apps/web/**`, `apps/api/pyproject.toml`, `apps/api/.python-version`, `apps/api/app/main.py`
- Create: `infra/docker/compose.yml`, `infra/docker/web.Dockerfile`, `infra/docker/api.Dockerfile`
- Test: `apps/web/src/app/page.test.tsx`, `apps/api/tests/test_health.py`

1. 用 create-next-app 初始化 `apps/web`，用 `uv init --package apps/api` 初始化 API；立即提交 `pnpm-lock.yaml` 和 `apps/api/uv.lock`。
2. 先写 Web 首页和 `/healthz` 的失败测试；运行：

```bash
pnpm --filter web test --run src/app/page.test.tsx
uv run --project apps/api pytest tests/test_health.py -q
```

预期：因页面与路由未实现失败。
3. 实现首页显示产品名称和 Mock 模式标识；实现 `/healthz` 返回 `{"status":"ok"}`。
4. Compose 加入 `web`、`api`、`worker`、`postgres`、`redis`、`object-storage`，为依赖服务配置 healthcheck；应用容器必须等待健康状态。
5. 运行 `pnpm lint && pnpm test && uv run --project apps/api pytest && docker compose -f infra/docker/compose.yml config`，预期全部通过。
6. Commit: `chore: bootstrap reproducible monorepo`

## Task 2: 建立数据库、迁移和工作区隔离基元

**Files:**
- Create: `apps/api/app/core/config.py`, `database.py`, `security.py`
- Create: `apps/api/app/modules/workspace/models.py`, `schemas.py`, `repository.py`, `service.py`
- Create: `apps/api/alembic.ini`, `apps/api/migrations/**`
- Test: `apps/api/tests/workspace/test_scope.py`, `test_migrations.py`

1. 失败测试必须证明：同一资源 ID 用错误 `workspace_id` 查询返回 `None`；没有上下文不能实例化工作区仓储。
2. 定义不可绕过的上下文：

```python
@dataclass(frozen=True)
class WorkspaceContext:
    workspace_id: UUID
    member_id: UUID | None
    role: Literal["admin", "editor", "viewer", "demo"]
```

3. 建立 `workspaces`、`workspace_members`、`workspace_access_codes`、`audit_logs` 基础表；所有主键 UUIDv7/时间有时区；邀请码表只含 `code_hash`，不得有明文列。
4. 仓储所有查询显式加入 `workspace_id == context.workspace_id`；增加禁止全表业务查询的架构测试。
5. 运行：

```bash
uv run --project apps/api alembic upgrade head
uv run --project apps/api pytest tests/workspace/test_scope.py tests/test_migrations.py -q
```

预期：迁移可在空库完成，跨工作区测试通过。
6. Commit: `feat: add workspace-scoped persistence foundation`

## Task 3: 独立邀请码、会话、角色和审计

**Files:**
- Create: `apps/api/app/modules/workspace/auth.py`, `permissions.py`, `router.py`
- Create: `apps/web/src/app/enter/page.tsx`, `apps/web/src/app/workspaces/[workspaceId]/settings/members/page.tsx`
- Test: `apps/api/tests/workspace/test_invites.py`, `test_permissions.py`
- E2E: `tests/e2e/workspace-access.spec.ts`

1. 测试覆盖：创建工作区得到一次性明文管理员邀请码；数据库只存 Argon2id 哈希；首次使用绑定显示名称；再次使用创建会话而不创建新成员；撤销后旧会话失效；管理员/编辑者/查看者权限矩阵正确；限流生效。
2. API：`POST /v1/workspaces`、`POST /v1/sessions/invite`、`DELETE /v1/sessions/current`、`POST /v1/workspaces/{id}/members/codes`、`PATCH /v1/workspaces/{id}/members/{member_id}`。
3. Cookie 配置 `HttpOnly`、`Secure`（本地开发例外）、`SameSite=Lax`、固定过期时间；CSRF 保护所有修改请求。
4. 审计记录邀请码签发/轮换/撤销、角色变化和成员操作，但不记录原码。
5. 运行：

```bash
uv run --project apps/api pytest tests/workspace -q -m "not e2e"
pnpm --filter e2e test workspace-access.spec.ts
```

预期：三个角色行为与设计一致，跨工作区 URL 返回 404。
6. Commit: `feat: implement invite-based workspace access`

## Task 4: 公开体验区和资源限额

**Files:**
- Create: `apps/api/app/modules/demo/service.py`, `seed.py`, `router.py`
- Create: `apps/web/src/app/demo/**`, `apps/web/src/components/demo-banner.tsx`
- Test: `apps/api/tests/demo/test_demo_isolation.py`, `test_demo_limits.py`
- E2E: `tests/e2e/demo.spec.ts`

1. 失败测试证明匿名访客只能读取固定 demo workspace，不能通过 ID 猜测访问私有工作区、上传文件、改示例数据或无限调用 AI。
2. 用人工生成数据建立抖音/小红书示例账号；所有示例必须标记 `synthetic=true`。
3. Demo 生成使用 Mock 模型并按匿名会话/IP 双层限额；响应显示“示例数据/Mock 输出”。
4. 运行 API 和 E2E 测试；预期所有写接口返回 403 或受控的临时副本，不影响种子数据。
5. Commit: `feat: add isolated public demo workspace`

## Task 5: 平台账号、栏目配置与版本继承

**Files:**
- Create: `apps/api/app/modules/content/account_models.py`, `account_service.py`, `account_router.py`
- Create: `apps/web/src/app/workspaces/[workspaceId]/accounts/**`
- Test: `apps/api/tests/content/test_account_config.py`

1. 测试平台枚举只能是 `douyin | xiaohongshu`；账号目标、指标权重、基准配置版本化；栏目默认继承账号，临时覆盖到期后恢复；历史内容保存当时版本 ID。
2. 建立 `platform_accounts`、`columns_campaigns`、`objective_profiles`、`benchmark_profiles` 表与 CRUD API。
3. 前端提供目标优先级拖拽、自定义权重、一键恢复账号默认；权重保存前后端都校验，启用指标总和归一化为 1。
4. 运行 `pytest tests/content/test_account_config.py` 和 Web 组件测试，预期版本恢复和越权均通过。
5. Commit: `feat: add versioned account and column configuration`

## Task 6: 单条内容详情与资产上传

**Files:**
- Create: `apps/api/app/modules/content/models.py`, `schemas.py`, `service.py`, `router.py`
- Create: `apps/api/app/core/storage.py`
- Create: `apps/web/src/app/workspaces/[workspaceId]/contents/**`
- Test: `apps/api/tests/content/test_content_detail.py`, `test_assets.py`
- E2E: `tests/e2e/content-detail.spec.ts`

1. 测试内容生命周期、当前草稿/最终发布版、软删除/回收站、同平台账号归属、资产 MIME/大小/权限及短期签名 URL。
2. 建立 `contents`、`content_assets`、`deleted_items`；禁止保存完整视频和小红书全部原图，只允许封面、截图、参考图、文档、作品链接。
3. 实现 `POST /v1/contents`、`GET/PATCH/DELETE /v1/contents/{id}`、资产预签名上传和上传确认；对象写入失败时不得保存失效数据库记录。
4. 单条详情页展示标题、文案、封面、平台、账号、栏目、发布时间、生命周期、当前数据完整度占位和后续模块入口。
5. E2E 创建→编辑→发布→回收站→恢复；预期审计日志完整，查看者不能修改。
6. Commit: `feat: deliver secure content detail workflow`

## Task 7: OpenAPI 类型、CI 与基础验收

**Files:**
- Create: `packages/shared-schemas/**`, `.github/workflows/ci.yml`
- Create: `docs/architecture/0001-modular-monolith.md`, `docs/architecture/data-isolation.md`
- Test: `apps/api/tests/architecture/test_openapi.py`, `tests/e2e/foundation-smoke.spec.ts`

1. 从 FastAPI OpenAPI 生成 TS client，CI 检查生成结果无漂移；禁止手工维护重复请求类型。
2. CI 运行 lint、typecheck、unit、integration、migration-from-empty、Compose config、secret scan。
3. 运行主计划 Gate A 及 foundation smoke；预期全绿。
4. 人工确认：匿名 Demo、三角色独立邀请码、抖音/小红书账号创建、单条内容详情均可演示。
5. Commit: `ci: enforce foundation quality and isolation gates`
