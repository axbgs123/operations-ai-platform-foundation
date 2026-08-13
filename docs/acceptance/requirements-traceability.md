# 产品验收需求追溯矩阵

验证日期：2026-08-05。状态只使用 `passed`、`partial`、`blocked`、`not_run`。自动化证据来自隔离临时环境、人工合成数据和 Mock Provider，不等同于真实平台、真实千问或独立非开发者验证。

| 需求编号 | 需求 | 自动化证据 | 当前状态 |
| --- | --- | --- | --- |
| UX-COPY-01 | 运营用户可切换易懂/专业文案并随时开关页面引导；偏好按成员隔离，风险语义不弱化 | 自动化已通过：Web 组件/单元测试、`workbench-guidance.spec.ts`（含 Professional Viewer 导入记录的只读/联系文案）、Viewer/错误状态及模式视觉基线、隔离 fresh-install/restart；限制：独立非开发者 Task 9B 仍为 `independent_non_developer_pending` | partial |

## AC-01

- 原始需求文字：无邀请码访客可以安全体验只读示例工作区。
- 对应模块：规范路由 `/demo`、`/enter`；Demo seed、Demo 隔离 API、公开 Demo 页面。
- 精确自动测试：`apps/api/tests/demo/test_demo_isolation.py`；`tests/e2e/public-demo-screenshot.spec.ts`。
- 人工验收步骤：未登录打开 Demo，浏览合成内容并尝试修改，说明只读边界。
- 证据路径：`tests/e2e/full-loop.spec.ts` 步骤 1—2；Task 10 自动化报告。
- 当前结果：`passed`。
- 已知限制：独立非开发者理解度仍为 `not_run`。
- 最后验证日期：2026-07-30。
- 验证环境：macOS、Chromium、隔离数据库、合成 Demo。

## AC-02

- 原始需求文字：独立邀请码、Admin/Editor/Viewer 角色、撤销与工作区隔离。
- 对应模块：规范路由 `/settings/members` 与全部私有路由；WorkspaceContext、成员、邀请码、审计。
- 精确自动测试：`apps/api/tests/workspace/test_scope.py`、`test_membership.py`；`workbench-navigation.spec.ts`。
- 人工验收步骤：分别用三种角色邀请码进入并核对可见入口；撤销后重试。
- 证据路径：角色矩阵 E2E；Task 10 自动化报告。
- 当前结果：`passed`。
- 已知限制：邀请码易用性尚未由独立参与者验证。
- 最后验证日期：2026-07-30。
- 验证环境：隔离 PostgreSQL、合成工作区。

## AC-03

- 原始需求文字：抖音和小红书账号、栏目与指标配置严格分开。
- 对应模块：规范路由 `/accounts`、`/columns`、`/settings`；平台指标注册表。
- 精确自动测试：`apps/api/tests/metrics/test_platform_isolation.py`；Workbench Scope 测试。
- 人工验收步骤：分别选择两平台账号，核对栏目、指标和卡片没有混算。
- 证据路径：`workbench-navigation.spec.ts`；`full-loop.spec.ts` 步骤 6—8。
- 当前结果：`passed`。
- 已知限制：未连接真实平台账号。
- 最后验证日期：2026-07-30。
- 验证环境：隔离数据库、合成双平台账号。

## AC-04

- 原始需求文字：手动、Excel/CSV、截图和 Capture Extension 导入内容与快照。
- 对应模块：规范路由 `/imports`、内容快照标签；ImportService、截图暂存、扩展上传。
- 精确自动测试：`apps/api/tests/imports/test_import_api.py`、`test_extension_capture.py`。
- 人工验收步骤：依次发现四种入口，检查暂存预览并确认合成数据。
- 证据路径：`metrics-import-analysis.spec.ts`、`extension-safe-capture.spec.ts`。
- 当前结果：`partial`。
- 已知限制：真实抖音/小红书页面尚未验证；真实扩展包创作者页面与 Windows/Edge 为 `not_run`；完整八阶段生命周期数据模型仍不足。
- 最后验证日期：2026-07-30。
- 验证环境：脱敏 Fixture、Mock OCR、隔离临时环境。

## AC-05

- 原始需求文字：动态基准、成熟度与完整度按平台、账号、类型和用户范围正确计算。
- 对应模块：规范路由 `/accounts/{account_id}`、内容快照标签；Benchmark、Maturity、Completeness。
- 精确自动测试：`apps/api/tests/metrics/test_benchmarks.py`、`test_completeness.py`。
- 人工验收步骤：切换范围并核对实际样本、分位门禁和缺失说明。
- 证据路径：`full-loop.spec.ts` 步骤 12—16；账号仪表盘视觉基线。
- 当前结果：`passed`。
- 已知限制：只使用合成样本，不代表生产数据分布。
- 最后验证日期：2026-07-30。
- 验证环境：隔离 PostgreSQL、固定合成指标。

## AC-06

- 原始需求文字：仪表盘按“状态—问题—原因—行动”展示，并只在门禁满足时显示图表。
- 对应模块：规范路由 `/`、`/accounts/{account_id}`、内容分析标签；受控 Workbench 读模型和 ChartGate。
- 精确自动测试：`workbench-overview.test.tsx`、`account-dashboard.test.tsx`、对比度测试。
- 人工验收步骤：由独立参与者解释四段含义，并比较有/无样本状态。
- 证据路径：`workbench-visual.spec.ts`、`workbench-mobile.spec.ts`。
- 当前结果：`partial`。
- 已知限制：自动合同通过；普通人的理解与完整八阶段生命周期表达仍待 Task 9B。
- 最后验证日期：2026-07-30。
- 验证环境：jsdom、Chromium、合成读模型。

## AC-07

- 原始需求文字：AI 分析引用实际 Evidence，样本不足时正确降级。
- 对应模块：规范路由 `/analysis`、内容分析标签；Analysis Evidence Bundle 与版本元数据。
- 精确自动测试：`apps/api/tests/analysis/test_evidence.py`、`test_degradation.py`。
- 人工验收步骤：打开引用与快照逐项核对，并观察单样本降级。
- 证据路径：`full-loop.spec.ts` 步骤 12—16；内容分析视觉基线。
- 当前结果：`partial`。
- 已知限制：真实千问 API 尚未运行；Catalog 仍为 `experimental`。
- 最后验证日期：2026-07-30。
- 验证环境：Mock Provider、合成 Evidence。

## AC-08

- 原始需求文字：RiskRAG 按平台、生命周期、来源等级返回可验证引用和建议。
- 对应模块：规范路由 `/preflight`、内容风控标签、`/risk-knowledge`；检索过滤与 Citation Validator。
- 精确自动测试：`test_retrieval.py`、`test_citations.py`、`test_evaluation.py`。
- 人工验收步骤：查看双平台合成扫描、来源等级、OCR 降级和免责声明。
- 证据路径：`risk-rag.spec.ts`；风险相关视觉基线。
- 当前结果：`partial`。
- 已知限制：固定合成评估只是工程回归门槛，不代表平台过审准确率。
- 最后验证日期：2026-07-30。
- 验证环境：Mock Embedding、固定合成评估集。

## AC-09

- 原始需求文字：标题、文案和封面风格可分别继承或关闭。
- 对应模块：规范路由 `/styles`、`/styles/{account_id}`；版本化 Style profile 与三项开关。
- 精确自动测试：`apps/api/tests/style_facts/test_style_inheritance.py`；`style-profile-center.test.tsx`。
- 人工验收步骤：逐项关闭继承并说明账号风格与爆款结构的区别。
- 证据路径：`full-loop.spec.ts` 步骤 19—23；风格视觉基线。
- 当前结果：`passed`。
- 已知限制：风格样本为人工合成内容。
- 最后验证日期：2026-07-30。
- 验证环境：隔离数据库、Mock Provider。

## AC-10

- 原始需求文字：L1—L5 事实确认、冲突和禁止视觉推断规则控制确定性生成。
- 对应模块：规范路由 `/facts`、生成事实步骤；Fact sources/items、冲突门禁。
- 精确自动测试：`test_conflicts.py`、`test_visual_prohibitions.py`、`test_text_generation.py`。
- 人工验收步骤：确认合成事实、观察冲突与 L5 限制，并寻找联网资料入口。
- 证据路径：`full-loop.spec.ts` 步骤 19—25；事实资料视觉基线。
- 当前结果：`partial`。
- 已知限制：自动联网检索未配置；Facts 细粒度账号/栏目范围不存在；当前只支持添加网页来源。
- 最后验证日期：2026-07-30。
- 验证环境：合成事实、Mock Provider、无外网。

## AC-11

- 原始需求文字：爆款候选只有人工确认后才能进入素材库并被生成引用。
- 对应模块：规范路由 `/viral-library`；Viral candidate、人工确认、library item。
- 精确自动测试：`apps/api/tests/analysis/test_viral.py`；`viral-library.test.tsx`。
- 人工验收步骤：比较确认前后视觉、文案与生成资格。
- 证据路径：`full-loop.spec.ts` 步骤 17—18；爆款视觉基线。
- 当前结果：`passed`。
- 已知限制：门槛只以合成指标验证，不代表因果。
- 最后验证日期：2026-07-30。
- 验证环境：隔离数据库、合成快照。

## AC-12

- 原始需求文字：标题、文案和四类封面完成生成、复核与保存。
- 对应模块：规范路由 `/generation`、内容生成标签；五步向导和 Text/Cover generation。
- 精确自动测试：`test_text_generation.py`、`test_cover_modes.py`、`generation-wizard.test.tsx`。
- 人工验收步骤：独立完成 Mock 五步生成，查看发布前门禁并保存草稿。
- 证据路径：`generation-workbench.spec.ts`；`full-loop.spec.ts` 步骤 24—30。
- 当前结果：`partial`。
- 已知限制：文本生成与正式 `content_id` 关联不足；真实千问和独立参与者保存流程均 `not_run`。
- 最后验证日期：2026-07-30。
- 验证环境：Mock 文本/图片 Provider、合成事实和风格。

## AC-13

- 原始需求文字：CSV、Markdown、JSON、ZIP 导出与受控恢复可用。
- 对应模块：规范路由 `/data-management/exports`；异步导出、校验和、恢复预览/确认。
- 精确自动测试：`test_csv.py`、`test_markdown.py`、`test_json_restore.py`。
- 人工验收步骤：下载便携格式并对 ZIP 执行恢复预览，核对秘密未继承。
- 证据路径：`backup-restore.spec.ts`；导出视觉基线。
- 当前结果：`passed`。
- 已知限制：模型密钥与向量按设计不继承，恢复后需重新配置和索引。
- 最后验证日期：2026-07-30。
- 验证环境：隔离 PostgreSQL/MinIO、合成资产。

## AC-14

- 原始需求文字：AI、识别或恢复任务失败时不破坏已保存数据。
- 对应模块：规范路由 `/settings/jobs` 与各暂存页；任务状态、事务回滚、补偿和幂等。
- 精确自动测试：`test_zip_restore_failures.py`、`test_generation_cache.py`、`test_extension_capture.py`。
- 人工验收步骤：触发合成失败后刷新原内容、快照与任务状态。
- 证据路径：`backup-restore.spec.ts`、`extension-safe-capture.spec.ts`。
- 当前结果：`passed`。
- 已知限制：旧 Embedding generation 的受控清理由既定保留策略后续处理。
- 最后验证日期：2026-07-30。
- 验证环境：隔离对象存储、故障注入。

## AC-15

- 原始需求文字：依据文档在新环境部署，发布树不含秘密和真实私有数据。
- 对应模块：规范路由 `/settings`、开源文档；Compose、迁移、Demo seed、allowlist、SBOM。
- 精确自动测试：`apps/api/tests/open_source/test_release_security.py`；Compose 配置门禁。
- 人工验收步骤：在未参与开发的机器按 README 部署并记录所有阻塞。
- 证据路径：`fresh-install.spec.ts`、`scripts/verify-fresh-install.sh`。
- 当前结果：`partial`。
- 已知限制：独立新机器、Windows/Chrome、Windows/Edge 和 macOS/Edge 真实运行均 `not_run`。
- 最后验证日期：2026-07-30。
- 验证环境：macOS Docker Desktop、隔离 Compose 项目。

## AC-16

- 原始需求文字：记录分析/采集耗时、反馈、采用状态和每周有效运营闭环。
- 对应模块：规范路由 `/`、分析与生成标签；Product events、Analytics、Mock 污染隔离。
- 精确自动测试：`test_effective_loops.py`、`test_events.py`。
- 人工验收步骤：真实独立参与者计时、反馈、采用建议并完成下一条草稿。
- 证据路径：`full-loop.spec.ts` 步骤 31—35；`test-session-template.md`。
- 当前结果：`not_run`。
- 已知限制：真实参与者时间、完成率和每周闭环不得由 Mock 推断；原因 `independent_non_developer_session_pending`。
- 最后验证日期：2026-07-30。
- 验证环境：自动合同为隔离 Compose；真实参与者环境未运行。

## AC-17

- 原始需求文字：运营智能体每天提出一项可解释建议，锁定单个平台账号，先展示计划再执行，并在权限、事实、风控和 Provider 边界内生成可人工复核的结果。
- 对应模块：规范路由 `/agent`、`/hotspots`；成员私有持久化聊天、严格意图编排、Daily Briefing、固定工具目录、热点截图人工确认、模型原生联网研究、Plan approval、持久化 Run/Step/Confirmation/Artifact、Worker fencing。
- 精确自动测试：`apps/api/tests/operations_agent/`、`apps/api/tests/hotspots/test_hotspot_capture.py`、`apps/api/tests/models/test_native_web_search.py`；`tests/e2e/operations-agent.spec.ts`；32 条双平台固定评估用例。E2E 同时验证发送“你好”、刷新恢复历史，再切换到原“任务与执行”完成九步闭环。
- 人工验收步骤：Editor 在“对话”中发送问题并恢复历史；切换到“任务与执行”查看每日建议；在公开热点榜用扩展截图、人工确认并选择同平台账号，核对联网引用和候选草稿；确认没有发布或支付入口。
- 证据路径：`docs/acceptance/operations-agent-evaluation.md`；`scripts/verify-fresh-install.sh` 的重启前后 ID 对比。
- 当前结果：`partial`。
- 已知限制：真实千问原生联网、真实第三方兼容模型、真实平台页面和独立非开发者智能体测试均 `not_run`；通用兼容模型不会被假定具备联网能力；聊天正文尚未进入 JSON/ZIP 跨机器恢复；自动抓榜、定时搜索、发布和支付未实现。
- 最后验证日期：2026-08-13。
- 验证环境：隔离 PostgreSQL/Redis/MinIO、Mock Provider、Chromium、人工合成数据。

## 状态汇总与不可越界结论

- AC-01—AC-17：`passed` 8；`partial` 8；`blocked` 0；`not_run` 1。UX-COPY-01：`partial` 1。
- UX-COPY-01 自动化验收已通过；独立非开发者 Task 9B 仍为 `independent_non_developer_pending`，因此不得标记为生产完成。
- 独立非开发者测试：`not_run`；原因：`independent_non_developer_session_pending`。
- 真实千问 API 尚未运行，Catalog 仍为 `experimental`。
- 真实抖音/小红书页面尚未验证；Windows/Edge 真实运行仍为 `not_run`。
- 运营智能体独立非开发者测试为 `not_run`；原因：`independent_non_developer_agent_session_pending`。
- 自动抓取热点榜、定时趋势搜索、自动发布和支付调用均未实现；当前热点流程要求用户截图并人工确认。
- `text-embedding-v4 没有确认的日期快照`，不得声称固定日期模型可重复。
- 自动联网检索、Facts 细粒度账号/栏目范围、完整八阶段生命周期、文本生成与正式 `content_id` 关联均为 `partial`。
- 自动化结果不代表生产平台过审率、真实模型质量或正式发布结论。
