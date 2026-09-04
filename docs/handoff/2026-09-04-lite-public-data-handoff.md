# 运营内容智能分析与生成平台：当前版本交接提示词

更新时间：2026-09-04

这份文件用于把项目交给新的 Codex 对话。项目已经是可运行的高完成度工程型 MVP，
不要根据 2026-07-21 的旧交接文档重新从第一阶段开始开发。

## 当前代码位置

- 本机工作目录：`/Users/baiyan1/Documents/Codex/operations-ai-platform-foundation-workbench-redesign`
- GitHub：`https://github.com/axbgs123/operations-ai-platform-foundation`
- 当前开发分支：`codex/lite-architecture`
- 本文编写前的功能基线：`cf0e4ab2eb22a9af72b9964adcb9a7bcbe9add64`
- GitHub `main` 尚未合并这批最新改动；从其他电脑接手时必须先切换到
  `codex/lite-architecture`。

本机还有两个不属于本次提交的未跟踪路径：`.superpowers/brainstorm/` 和
`task-6-rereview-round-1.md`。不要读取、修改、删除、暂存或打包它们。

## 产品现在能做什么

产品面向抖音和小红书运营团队，核心闭环是：

`记录内容 → 回收数据 → 分析问题 → 沉淀策略资产 → 生成内容 → 发布前检查 → 再次回收数据`

当前已经具备：

- 团队创建、会话恢复、邀请码加入、Admin/Editor/Viewer 权限和工作区隔离；
- 两级工作台导航、易懂/专业文案、可随时开关的页面引导；
- 双平台账号、栏目/活动、内容库、手动与表格导入、截图识别、动态基准和分析；
- 爆款素材、账号风格、事实资料、标题/文案/封面生成和发布前风控；
- 可保存聊天记录的运营智能体，以及需要用户批准后才执行的原任务工作流；
- 千问、OpenAI-compatible 文本模型和智谱 GLM-5.3-Flash 快捷配置；
- 热点榜截图确认与支持模型原生联网搜索的热点创作流程；
- Chrome/Edge 浏览器采集扩展、快捷键截图、全页采集和人工确认；
- TikHub 适配器：作品公开数据定时回收、对标账号、关键词热点搜索、评论需求分析、
  日报和相对爆款预警；
- CSV、Markdown、JSON 等导出，以及完整版保留的高级备份、任务与治理能力。

产品不自动发布内容，不保存平台 Cookie，也不采集创作者后台非公开数据。

## 当前架构

代码架构仍是模块化单体，FastAPI 是业务规则和权限的唯一边界，Next.js 负责工作台，
PostgreSQL/pgvector 保存结构化数据。推荐运行轻量版：

- PostgreSQL/pgvector：384 MiB 上限；
- FastAPI：640 MiB 上限；
- Next.js：256 MiB 上限；
- 不常驻 Redis、MinIO 和独立 Worker；同步任务由单实例 API 执行，文件写入本地卷。

轻量版已在隔离环境实测三个容器合计约 279 MiB，适合个人或少量成员低频使用。
完整版代码仍保留，用于需要队列、对象存储、高级恢复、删除审计和任务运维时升级。

## 最近完成的功能

当前分支最近五个功能提交：

1. `56f8114`：轻量部署与必要安全边界；
2. `79a73b2`：智谱 GLM-5.3-Flash 模型预设；
3. `ff7cce0`：TikHub 公开作品数据采集；
4. `c0893c4`：对标账号、评论需求、热点搜索、日报与预警；
5. `cf0e4ab`：公开数据智能闭环 E2E 与最终回归。

TikHub 只实现为可替换的 `PublicDataProvider`，密钥保存在后端。当前自动化验收使用
Mock/Fake Transport，没有调用真实 TikHub、真实平台或计费接口。

## 验收边界

自动化测试和隔离环境回归已经覆盖主要功能，但必须诚实保留以下状态：

- 需求追溯矩阵当前为 8 项 `passed`、8 项 `partial`、1 项 `not_run`；
- 独立非开发者 Task 9B 尚未完成；
- 真实千问、真实 TikHub、真实抖音/小红书页面未完成正式验收；
- Windows/Edge 的真实运行仍未验证；
- 真实模型效果、费用、限流和平台过审率不能由 Mock 测试推断；
- 文本生成与正式 `content_id` 的完整关联、Facts 账号/栏目级范围和完整八阶段生命周期
  仍是已知产品缺口；
- 轻量版面向单实例低并发，不应宣传为生产级高可用系统。

接手时优先阅读：

1. `README.md`
2. `docs/open-source/lite-deployment.md`
3. `docs/open-source/public-data-collection.md`
4. `docs/open-source/operations-agent-chat.md`
5. `docs/open-source/openai-compatible-model-configuration.md`
6. `docs/acceptance/requirements-traceability.md`
7. 与本次任务直接相关的设计和计划文件

## 本地运行状态

本文提交前，本地 Compose 项目 `operations_ai_local_lite_20260903` 已关闭。容器和网络已
移除，但以下数据卷仍保留：

- `operations_ai_local_lite_20260903_postgres-data`
- `operations_ai_local_lite_20260903_local-storage-data`

不要使用 `down --volumes`，除非用户明确确认要永久删除团队数据。

需要恢复原本地实例时，在仓库根目录执行：

```bash
docker compose --project-name operations_ai_local_lite_20260903 \
  -f infra/docker/compose.lite.yml up -d --no-build
```

如果代码或镜像已经改变，应先顺序构建 `api` 和 `web`，再使用 `up -d --no-build`。

## 可直接粘贴到新对话的提示词

```text
请接手“运营内容智能分析与生成平台”项目。

本机工作目录：
/Users/baiyan1/Documents/Codex/operations-ai-platform-foundation-workbench-redesign

GitHub：
https://github.com/axbgs123/operations-ai-platform-foundation

当前应使用分支：codex/lite-architecture

开始前请完整阅读：
1. docs/handoff/2026-09-04-lite-public-data-handoff.md
2. README.md
3. docs/open-source/lite-deployment.md
4. docs/open-source/public-data-collection.md
5. docs/acceptance/requirements-traceability.md
6. 与当前任务直接相关的设计、计划和 AGENTS.md

这是已经可运行的高完成度工程型 MVP，不要重新从零访谈，不要按旧交接文档从基础
Task 开始，也不要擅自重写架构。先只读检查当前分支、HEAD、上游和工作区状态，再用
中文简要汇报：你理解的现状、当前真实边界、建议下一步和预计影响。

必须保留这些约束：抖音与小红书指标分开；所有真实业务数据按 workspace 隔离；
TikHub 只采集公开数据且不负责发布；模型和 TikHub 密钥只留在后端；轻量版默认只运行
PostgreSQL、FastAPI、Next.js；没有用户明确授权时不得调用真实计费 API、推送、合并或
删除 Docker 数据卷。

本机的 .superpowers/brainstorm/ 和 task-6-rereview-round-1.md 是用户未跟踪文件，
不得读取、修改、删除、暂存或打包。不要触碰无关改动。

当前本地站点已关闭，但 operations_ai_local_lite_20260903 的 PostgreSQL 和本地文件卷
仍保留。恢复时不得使用 --volumes。先等待我给出具体下一项需求；收到需求后，复用
现有模块化单体和适配器，不要为了“完整架构”重新增加常驻 Redis、MinIO 或 Worker。
完成改动后进行与风险相称的测试，单独提交并汇报；除非我明确要求，不要推送或合并。
```
