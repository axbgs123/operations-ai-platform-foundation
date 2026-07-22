# 运营内容智能平台：新对话交接说明

更新时间：2026-07-22

## 给新对话中的 AI

你正在接手一个已经完成需求澄清、产品复核、技术规划和第一阶段开发的项目。不要重新从零访谈，不要重新生成产品设计或开发计划，也不要把项目误判为尚未开始。

工作目录：

`/Users/baiyan1/Documents/Codex/operations-ai-platform-foundation`

开始前完整阅读：

1. `docs/handoff/2026-07-21-operations-ai-project-handoff.md`
2. `docs/superpowers/specs/2026-07-20-operations-ai-platform-design.md`
3. `docs/superpowers/plans/2026-07-21-operations-ai-platform-master-plan.md`
4. `docs/superpowers/plans/2026-07-21-metrics-import-analysis-plan.md`
5. 当前范围内的 `AGENTS.md` 和被触发技能的完整说明。

随后运行只读 Git 检查，简短汇报理解和仓库状态，然后直接从 Metrics/Import/Analysis 计划 Task 1 开始。需求和计划已经批准，不需要再次等待“设计文档通过”。实施必须遵循计划中的 TDD、验证和逐任务提交要求。

## 用户与项目目标

- 用户是 2027 届数字媒体技术本科生，秋招方向优先级为产品、运营/编导、AIGC 内容。
- 用户负责需求发现、产品判断、模型选择、Prompt、测试和迭代，Codex 协助设计与编码；作品集不得包装为用户独立完成全部开发。
- 项目优先级：秋招作品集第一，GitHub 开源第二，真实团队长期使用第三。
- 期望地点杭州，次选上海；目标首份正式工作不低于 6000 元。
- 目标是在 2026-08-10 左右形成可公开演示的 Beta，但不能为了日期虚报完整功能。

## 产品目标和核心闭环

产品服务 3—10 人运营团队，支持抖音和小红书。核心闭环：

内容生产 → 发布记录 → 数据采集 → 动态基准与分析 → 爆款人工确认 → 策略复用 → 受风格、事实和风控约束的新内容生成。

关键约束：

- 抖音与小红书的指标、基准、内容类型、RAG 和分析完全隔离。
- 所有真实业务数据按 `workspace_id` 隔离，跨工作区资源返回 404。
- 私有工作区使用独立邀请码和 admin/editor/viewer 三角色，不使用邮箱账号系统。
- 事实约束优先级：已确认事实 > 平台风控 > 账号/栏目风格 > 爆款结构。
- AI 只能解释确定性计算和已有证据；证据不足时必须明确降级，不能编造。
- 生成标题、文案、封面默认沿用历史风格，三者可分别关闭，并支持一键选项。
- 支持文档、图片、链接、文字和参考图作为生成事实来源。
- 风控采用确定性规则＋平台隔离 RAG，并输出可验证引用和免责声明。
- 截图采集最终需要浏览器扩展的安全模式和可选一键模式；识别结果仍须人工确认。
- 首期是 Web 产品；桌面客户端、App 和本地电脑操作 Agent 后续复用同一 API。

## 当前真实进度

完整实施计划共 46 个任务，已完成 Foundation 的 7 个任务，按任务数约 15%。工程底座完成度高于用户可感知业务完成度。

已经完成：

- pnpm/uv monorepo、Next.js、FastAPI、PostgreSQL、Redis、MinIO、Celery、Docker Compose。
- 数据库迁移及工作区隔离基础。
- 邀请码登录、独立成员码、admin/editor/viewer 权限与 CSRF。
- 完全隔离且标注合成数据/Mock 输出的公开 Demo。
- 抖音和小红书账号、目标与指标优先级、默认 30 条动态基准配置、栏目/活动临时覆盖及版本历史。
- 单条作品详情、草稿/发布/归档/软删除/恢复、发布快照。
- 封面、截图、参考图、文档的 MinIO 预签名上传与短期下载地址。
- OpenAPI 自动生成 TypeScript 合同，前端不手写重复接口类型。
- CI、架构约束、数据隔离说明和 Foundation Gate A 验收清单。

尚未完成的核心业务：

- 平台指标注册表、真实运营数据快照和成熟度。
- 动态统计基准、Excel/CSV 暂存导入、截图 OCR 暂存。
- 折线图/仪表盘、爆款候选与人工确认、证据化 AI 分析。
- 风格档案、事实资料、标题/文案/四种封面生成。
- 平台风控 RAG。
- Chrome/Edge 数据采集扩展与一键截屏。
- 导出、完整备份恢复、可观测性、开源发布材料和非开发者测试。

## Git 与验证状态

- 当前分支：`main`
- 当前功能基线提交：`503c1a8 ci: enforce foundation quality and isolation gates`；其后仅允许有本交接文档更新提交。
- Foundation 功能分支已经合并并删除。
- 本交接文档提交后，`main` 比 `origin/main` 领先 9 个提交，尚未推送。
- 当前 `origin` 是本机路径 `/Users/baiyan1/Documents/文稿`，不是 GitHub 远程仓库。未经用户确认不要推送、替换远程或创建公开仓库。
- 最近一次合并后验证：Web 7/7、API 47/47、Playwright 4/4；OpenAPI 漂移、lint、typecheck、Alembic、密钥扫描均通过。
- API/Web Docker 镜像构建和 Compose 健康检查通过。
- 本机 Codex 桌面终端可能只把 `pnpm` 包装器加入 PATH；若生命周期脚本提示找不到 Node，在本地命令 PATH 前加入 Codex bundled Node 目录，不要把本机绝对路径写入仓库。

重要提交：

- `2bd9e76`：可复现 monorepo
- `58eeefc`：工作区持久化基础
- `4eada25`：邀请码与权限
- `7f9b65d`：公开 Demo
- `2bfaa31`：双平台账号与版本化配置
- `56475e5`：安全作品详情与素材流程
- `503c1a8`：OpenAPI、CI 与 Foundation 验收

## 新对话应当执行的下一步

从干净的 `main` 创建新分支，例如 `codex/metrics-import-analysis`，然后执行：

`docs/superpowers/plans/2026-07-21-metrics-import-analysis-plan.md`

第一个任务是“平台指标注册表与派生指标”：

1. 先写抖音/小红书指标隔离、内容类型兼容性、空值和派生指标的失败测试。
2. 建立后端确定性指标注册表和模型。
3. 建立 `packages/platform-metrics`，前端只消费展示元数据，不复制计算公式。
4. 运行任务规定的测试及现有回归测试。
5. 只提交当前 Task 1，再继续 Task 2 快照追加、成熟度和完整度。

不要跳过数据层直接做 AI 分析或漂亮图表。动态基准、图表、爆款和 AI 分析都依赖正确的指标与快照。

## 可直接粘贴到新对话的提示词

```text
请接手当前工作区中的“运营内容智能分析与生成平台”项目，工作目录是：
/Users/baiyan1/Documents/Codex/operations-ai-platform-foundation

请先完整阅读：
1. docs/handoff/2026-07-21-operations-ai-project-handoff.md
2. docs/superpowers/specs/2026-07-20-operations-ai-platform-design.md
3. docs/superpowers/plans/2026-07-21-operations-ai-platform-master-plan.md
4. docs/superpowers/plans/2026-07-21-metrics-import-analysis-plan.md

不要重新做需求访谈，不要重新写设计文档或开发计划。先只读检查 Git 状态，简短复述当前进度、下一项任务和你会使用的技能。确认工作区干净后，从 main 创建 codex/metrics-import-analysis 分支，严格使用 executing-plans 和 test-driven-development，从 Metrics/Import/Analysis 计划 Task 1“平台指标注册表与派生指标”开始执行。每次只完成一个 Task，运行规定验证、提交后向我汇报，再继续下一项。不要推送远程仓库，不要使用真实模型密钥或真实私有运营数据。
```
