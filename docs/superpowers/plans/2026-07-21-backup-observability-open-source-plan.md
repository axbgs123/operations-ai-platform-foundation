# Backup、Observability 与 Open-source Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 恢复功能必须先证明失败时整体回滚，才允许处理真实工作区备份。

**Goal:** 完成可验证的导出/备份/恢复、产品成功指标、运维安全、Docker 一键部署和可信的 GitHub 开源交付。

**Architecture:** Exports 通过版本化 manifest 和校验和输出；恢复先解包到隔离暂存、验证和预览，再单事务/补偿操作提交；产品事件只记录最少必要字段；监控日志结构化且脱敏；发布资产全部使用合成或授权数据。

**Tech Stack:** FastAPI/Celery、PostgreSQL、S3、ZIP/JSON/CSV/Markdown、OpenTelemetry 兼容日志指标；Docker Compose、GitHub Actions、Playwright。

**Global Constraints:** JSON 不含媒体、密钥、邀请码、会话和向量；ZIP 包含原始媒体/知识文档但仍不含秘密；向量恢复后重建。工作区删除需要管理员二次确认并删除数据库、向量和媒体。

## Task 1: CSV 与 Markdown 导出

**Files:**
- Create: `apps/api/app/modules/exports/tabular.py`, `report.py`, `router.py`
- Test: `apps/api/tests/exports/test_csv.py`, `test_markdown.py`

1. 测试 CSV 包含内容与运营数据、保留空值/时区/平台字段、不跨工作区；Markdown 单条报告含分析版本、数据证据、引用和免责声明。
2. 异步导出产生短期签名 URL，过期后不可访问；文件名防注入。
3. Commit: `feat: export portable data and analysis reports`

## Task 2: JSON 轻量备份与恢复预览

**Files:**
- Create: `apps/api/app/modules/exports/manifest.py`, `json_backup.py`, `restore_preview.py`
- Test: `apps/api/tests/exports/test_json_backup.py`, `test_json_restore.py`

1. 定义 `schema_version/product_version/exported_at/workspace/records`；测试 JSON 不包含资产正文、密钥、邀请码、会话、哈希和向量。
2. 恢复前校验版本、引用完整性和冲突，预览 `create | overwrite | skip | conflict`；用户可选新工作区或合并。
3. 失败注入测试必须证明事务整体回滚。
4. Commit: `feat: add versioned lightweight json backup`

## Task 3: ZIP 完整备份、校验和与恢复

**Files:**
- Create: `apps/api/app/modules/exports/zip_backup.py`, `zip_restore.py`, `checksums.py`
- Test: `apps/api/tests/exports/test_zip_backup.py`, `test_zip_restore.py`, `test_zip_security.py`

1. ZIP 固定结构：`manifest.json`、`data.json`、`assets/**`、`knowledge/**`、`checksums.json`；测试每个文件 SHA-256、缺失/篡改拒绝、Zip Slip 和压缩炸弹防护。
2. 恢复先到隔离临时前缀；数据库提交成功后再移动对象；对象移动失败执行补偿并保持原工作区不变。
3. 不恢复向量；恢复成功后排队按当前 Embedding 配置重建，并在完成前显示“知识索引重建中”。
4. Commit: `feat: deliver checksummed full workspace backup`

## Task 4: 回收站、保留策略和工作区删除

**Files:**
- Create: `apps/api/app/modules/exports/deletion.py`, `retention_tasks.py`
- Test: `apps/api/tests/exports/test_deletion.py`

1. 测试软删除、恢复、最终删除时间；截图确认后立即/定时/证据保留三种策略；删除工作区需要管理员与二次确认 token。
2. 删除任务清理结构化数据、pgvector、对象和缓存；失败可重试且审计每个阶段，不留下可访问孤儿对象。
3. Commit: `feat: enforce recoverable deletion and retention policies`

## Task 5: 产品事件和北极星指标

**Files:**
- Create: `apps/api/app/modules/analytics/events.py`, `north_star.py`, `analytics_router.py`
- Create: `apps/web/src/components/feedback/**`
- Test: `apps/api/tests/analytics/test_events.py`, `test_effective_loops.py`

1. 测试首次分析耗时、采集耗时、分析有用/无用、建议保存/采用、生成采用/修改幅度、完整度和留存事件。
2. “有效运营闭环”只在同一工作区内满足：已发布内容+至少一个真实确认快照+查看 AI 分析+保存建议或生成下一条草稿；重复事件不得重复计数。
3. 事件不保存完整文案、截图或模型密钥；公开 demo 不计入真实使用指标。
4. Commit: `feat: measure effective weekly operations loops`

## Task 6: 结构化日志、限流和任务运维

**Files:**
- Create: `apps/api/app/core/logging.py`, `rate_limit.py`, `observability.py`
- Create: `apps/web/src/app/workspaces/[workspaceId]/settings/jobs/page.tsx`
- Test: `apps/api/tests/core/test_log_redaction.py`, `test_rate_limit.py`, `test_job_recovery.py`

1. 日志测试自动脱敏邀请码、Authorization、Cookie、API Key、完整敏感文案和用户文件内容；包含 request/task/workspace 的非敏感关联 ID。
2. 登录、AI、上传/识别、导出分别限流；后台任务支持取消、有限重试、死信诊断和管理员查看。
3. health/readiness 区分应用存活与 Postgres/Redis/S3 可用性。
4. Commit: `feat: add privacy-safe operations observability`

## Task 7: Docker 部署、迁移与示例数据

**Files:**
- Modify: `infra/docker/compose.yml`, Dockerfiles, `.env.example`
- Create: `infra/docker/entrypoints/**`, `apps/api/app/demo_seed.py`
- Test: `tests/e2e/fresh-install.spec.ts`, `scripts/verify-fresh-install.sh`

1. 镜像多阶段构建、非 root 用户、明确 tag/digest、健康检查、持久卷；启动时以独立 migration job 执行 Alembic，不允许多个 Web worker 竞争迁移。
2. `.env.example` 每项有用途与安全默认值；Mock 模式无需外部密钥即可启动。
3. 在干净卷执行 Compose→迁移→示例种子→公开 demo 闭环→停止→再次启动验证持久化。
4. Commit: `chore: make fresh docker deployment reproducible`

## Task 8: 开源文档、许可证和供应链安全

**Files:**
- Create: `README.md`, `LICENSE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`
- Create: `docs/architecture/system.md`, `data-model.md`, `model-adapters.md`
- Create: `docs/open-source/deployment.md`, `backup-restore.md`, `risk-knowledge.md`
- Modify: `.github/workflows/ci.yml`

1. README 包含产品边界、截图、架构、快速开始、Mock/真实模型差异、扩展安装、数据隐私和“不保证平台审核通过”。
2. 许可证选择前检查所有直接依赖和示例资产兼容性并记录决定；公共知识库只打包可授权来源元数据/摘要。
3. CI 加 secret scan、依赖审计、SBOM、镜像扫描和构建产物检查；Git 历史扫描无秘密。
4. 明确作品集贡献说明：用户负责需求、判断、测试和迭代，AI 协助设计与编码；不得声称用户独立完成全部开发。
5. Commit: `docs: prepare trustworthy open-source release`

## Task 9: 全产品验收映射与非开发者测试

**Files:**
- Create: `docs/acceptance/requirements-traceability.md`, `docs/acceptance/test-session-template.md`
- E2E: `tests/e2e/full-loop.spec.ts`, `tests/e2e/backup-restore.spec.ts`

1. 将设计文档第 25 节 16 条逐条映射到自动测试名、人工步骤和证据路径；不允许只写“已完成”。
2. 全闭环 E2E：私有邀请码→双平台账号→内容/快照→动态基准→AI 分析→确认爆款→事实资料→风格生成→风控复检→草稿→导出→ZIP 恢复。
3. 邀请一名非开发者使用 AI 科技示例/授权数据测试，记录阻塞点、首次分析时间、采集时间、识别修正、分析反馈；初始目标未达到也如实记录。
4. 运行主计划 Gate A—D 和 `superpowers:verification-before-completion`；修复所有失败后才能声明完整可用。
5. Commit: `test: verify complete product acceptance`
