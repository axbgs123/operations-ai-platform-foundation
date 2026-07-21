# 运营内容智能分析与生成平台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 每完成一个任务必须先运行该任务列出的验证命令；禁止跨过失败测试继续堆功能。

**Goal:** 把已批准的产品设计实现为可公开体验、可用邀请码进入私有工作区、支持抖音与小红书独立分析、内容生成、事实约束、风控 RAG、截图采集扩展和完整备份恢复的开源产品。

**Architecture:** 单仓库、模块化单体。Next.js 负责 Web；FastAPI 负责所有业务规则和统一 API；Celery/Redis 执行异步任务；PostgreSQL/pgvector 保存结构化数据和向量；对象存储通过 S3 接口隔离；Chrome/Edge Manifest V3 扩展只采集用户当前可见、已确认的页面截图。Web、扩展及未来客户端只能调用 API，不复制业务规则。

**Tech Stack:** Node.js 22 LTS（满足 Next.js 16 的 Node ≥20.9 要求）、pnpm workspace、Next.js 16 App Router、TypeScript、Tailwind CSS、Vitest、Testing Library、Playwright；Python 3.12、uv、FastAPI、Pydantic 2、SQLAlchemy 2、Alembic、Celery 5.6、pytest、Ruff、mypy；PostgreSQL 18、pgvector 0.8.2、Redis 8、S3 兼容对象存储；Chrome Extension Manifest V3；Docker Compose v2。

## Global Constraints

- 产品设计基线：`docs/superpowers/specs/2026-07-20-operations-ai-platform-design.md`。任何实现冲突均先回到该文档确认，不隐式改需求。
- 所有业务表必须带 `workspace_id`；仓储方法必须显式接收 `WorkspaceContext`；资源 ID 命中但工作区不符时返回 404。
- `douyin` 与 `xiaohongshu` 的指标定义、内容类型、快照成熟度、基准、RAG 索引和分析绝不混用。
- 事实约束优先级固定为：已确认事实 > 平台风控 > 账号/栏目风格 > 爆款结构。
- AI 输出必须通过 Pydantic schema；没有证据时输出“证据不足”，不能编造数据、事实或规则引用。
- 邀请码、会话令牌、模型密钥只保存强哈希或密文；不写日志、不出现在 URL、不进入导出。
- 所有异步写任务使用幂等键；任务失败不得破坏已确认数据。
- 依赖版本由 `pnpm-lock.yaml` 与 `uv.lock` 固定；Docker 镜像在实现时固定到明确 tag/digest，禁止部署使用 `latest`。
- 每个任务遵循 Red → Green → Refactor；提交只包含当前任务及必要锁文件，不包含 `.DS_Store`、密钥或真实运营数据。
- 首个验证数据集为人工生成的 AI 科技账号；服装案例只用于事实一致性验收。

## Repository Target

```text
apps/
  web/                         # Next.js 页面、组件、API client
  api/                         # FastAPI 模块化单体、Celery worker
  extension/                   # Chrome/Edge Manifest V3
packages/
  shared-schemas/              # OpenAPI 生成的 TS 类型与事件 schema
  platform-metrics/            # 前端只读展示元数据；计算仍在 API
infra/
  docker/                      # compose、镜像、初始化脚本
docs/
  architecture/                # ADR、模块边界、数据模型
  open-source/                 # 部署、扩展安装、贡献与安全说明
tests/
  e2e/                         # 跨 Web/API 的 Playwright 流程
```

## Plan Index and Dependency Order

| 顺序 | 实施计划 | 产出 | 前置 |
|---|---|---|---|
| 1 | `2026-07-21-foundation-workspace-content-plan.md` | 仓库脚手架、基础设施、公开体验区、邀请码权限、账号/栏目/内容 | 无 |
| 2 | `2026-07-21-metrics-import-analysis-plan.md` | 快照、动态基准、Excel/截图暂存、图表数据、爆款与分析 | 1 |
| 3 | `2026-07-21-style-facts-generation-plan.md` | 风格版本、事实清单、模型适配、标题/文案/四种封面生成 | 1、2 的内容资产 |
| 4 | `2026-07-21-risk-rag-plan.md` | S1—S5 知识生命周期、规则扫描、RAG 引用、评估集 | 1；与 3 并行开发，集成时先于生成发布门禁 |
| 5 | `2026-07-21-capture-extension-plan.md` | 安全模式、一键模式、截图识别、人工确认、页面失配降级 | 1、2 的导入 API |
| 6 | `2026-07-21-backup-observability-open-source-plan.md` | CSV/Markdown/JSON/ZIP、恢复、产品事件、部署与开源交付 | 1—5 |

这张表是技术依赖顺序，不是对外产品版本划分。各计划完成后仍以设计文档第 25 节的 16 条整体验收为发布门槛。

## Cross-plan API Contracts

所有响应使用：

```json
{
  "data": {},
  "meta": {"request_id": "uuid", "task_id": null},
  "error": null
}
```

所有异步任务返回 `202` 和：

```json
{
  "data": {"task_id": "uuid", "status": "queued"},
  "meta": {"request_id": "uuid", "task_id": "uuid"},
  "error": null
}
```

任务状态只能是 `queued | running | succeeded | failed | cancelled | retrying`。错误使用稳定代码，例如 `WORKSPACE_SCOPE_MISMATCH`、`INSUFFICIENT_SAMPLE`、`FACT_CONFLICT`、`NO_ACTIVE_RISK_EVIDENCE`。

## Release Gates

### Gate A — 每个子计划

```bash
pnpm lint
pnpm typecheck
pnpm test
uv run --project apps/api ruff check .
uv run --project apps/api mypy app
uv run --project apps/api pytest
docker compose -f infra/docker/compose.yml config
```

预期：全部退出码为 0；测试不得依赖外网或真实模型密钥。

### Gate B — 整体端到端

```bash
docker compose -f infra/docker/compose.yml up -d --build
pnpm --filter e2e test
pnpm --filter extension test
docker compose -f infra/docker/compose.yml down
```

预期：设计文档 22.3 的端到端流程全部通过；服务停止后没有未提交的生成物。

### Gate C — 安全与隔离

```bash
uv run --project apps/api pytest -m security
uv run --project apps/api pytest -m isolation
pnpm audit --prod
uv run --project apps/api pip-audit
```

预期：跨工作区、跨平台、跨账号风格串用测试为 0；不存在高危生产依赖漏洞。无法修复的上游告警必须记录 ADR 和缓解措施，不能静默忽略。

### Gate D — 开源交付

在一台没有项目缓存的新环境按 README 执行 Docker Compose 启动；使用示例数据完成一次有效运营闭环；扫描 Git 历史和当前树，确认无密钥、邀请码、真实私有数据和版权不明的风控材料。

## Official Technical References

- Next.js 安装与 Node 要求：https://nextjs.org/docs/app/getting-started/installation
- Next.js 16 升级说明：https://nextjs.org/docs/app/guides/upgrading/version-16
- FastAPI 安装与运行：https://fastapi.tiangolo.com/tutorial/
- uv 项目与锁文件：https://docs.astral.sh/uv/guides/projects/
- pgvector：https://github.com/pgvector/pgvector
- Celery Redis：https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html
- Chrome Manifest V3：https://developer.chrome.com/docs/extensions/develop/migrate/what-is-mv3
- Chrome `captureVisibleTab`：https://developer.chrome.com/docs/extensions/reference/api/tabs#method-captureVisibleTab
- Docker Compose：https://docs.docker.com/compose/

## Final Definition of Done

- 六份子计划任务全部完成且各自验证通过。
- 设计文档第 25 节的 16 条验收逐条映射到自动测试或有证据的人工验收记录。
- `README.md` 能让新用户在无真实模型密钥时用 Mock 模式跑通公开体验；配置受支持模型后能跑通私有工作区完整闭环。
- 至少由一名非开发者完成 AI 科技账号真实流程测试，记录首次分析耗时、采集耗时、识别修正和分析反馈；初始目标只能作为验证假设展示。
- 发布前运行 `superpowers:verification-before-completion`，保存完整验证输出，随后再决定合并、PR 或发布。
