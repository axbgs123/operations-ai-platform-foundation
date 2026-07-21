# Metrics、Import 与 Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 计算规则先用纯函数测试锁定，再接数据库与 UI。

**Goal:** 完成双平台独立指标、可追加快照、动态基准、数据导入、条件图表、爆款确认和有证据的 AI 分析闭环。

**Architecture:** 平台指标注册表与统计计算是确定性领域层；导入先进入 staging，再经人工确认事务写入；AI 只解释已经计算的特征和检索证据，不代替统计计算。

**Tech Stack:** FastAPI/SQLAlchemy/Pandas 或 openpyxl、Celery/Redis、Pydantic；Next.js、ECharts、TanStack Query；pytest/Vitest/Playwright。

**Global Constraints:** 抖音/小红书、图文/视频、不同成熟度绝不混算。1 条快照只分析当前值，≥2 条才生成趋势。样本 `<5` 只显示原始数据，`5—9` 低置信度，`≥10` 正常分析。

## Task 1: 平台指标注册表与派生指标

**Files:**
- Create: `apps/api/app/modules/metrics/definitions.py`, `models.py`, `schemas.py`
- Create: `packages/platform-metrics/src/index.ts`
- Test: `apps/api/tests/metrics/test_definitions.py`, `test_derived_metrics.py`

1. 参数化测试锁定设计文档第 8 节的默认指标、允许空值、自定义指标，以及平台/内容类型不兼容时拒绝写入。
2. 定义 `MetricDefinition`，包含 `platform`、`content_type`、`key`、`unit`、`aggregation`、`higher_is_better`；派生指标仅在分母有效时计算。
3. TS 包只由 OpenAPI/注册表生成展示元数据，不复制计算公式。
4. 运行 `pytest tests/metrics/test_definitions.py tests/metrics/test_derived_metrics.py -q`；预期双平台隔离用例全部通过。
5. Commit: `feat: define isolated platform metric registries`

## Task 2: 快照追加、成熟度与数据完整度

**Files:**
- Create: `apps/api/app/modules/metrics/snapshot_service.py`, `maturity.py`, `router.py`
- Test: `apps/api/tests/metrics/test_snapshots.py`, `test_maturity.py`

1. 测试推荐节点 1h/24h/72h/7d 非强制；新增永不覆盖；自定义时间映射到比较区间；低置信度字段为空且不入基准；发布时间晚于采集时间拒绝。
2. 建立 `data_snapshots`、`snapshot_metric_values`，保存原始值、标准值、来源、确认状态、OCR 置信度和原截图资产 ID。
3. 实现快照 CRUD/确认 API；写入后通过 outbox 触发基准刷新，保证数据库提交与任务一致。
4. 运行快照测试；预期只有已确认且有效的值参与统计。
5. Commit: `feat: add append-only metric snapshots`

## Task 3: 动态基准、分位数和可选综合指数

**Files:**
- Create: `apps/api/app/modules/metrics/benchmark.py`, `scoring.py`, `benchmark_tasks.py`
- Test: `apps/api/tests/metrics/test_benchmark.py`, `test_scoring.py`, `test_platform_isolation.py`

1. 用固定数组测试中位数、P75、P90、历史分位、最近 N 条（默认 30）、日期/全部历史、栏目筛选、成熟度匹配、缺失指标权重重归一化。
2. `BenchmarkInput` 必须包含 `workspace_id/platform/account_id/content_type/maturity_bucket/range/version`；缺一项即拒绝计算。
3. 综合指数默认关闭；启用时只对账号内历史分位加权，并返回说明文本“非平台官方评分或客观内容质量分”。
4. 持久化 `benchmark_runs` 的样本 ID、样本量、范围、分位值、权重与算法版本，使历史可复现。
5. 运行：

```bash
uv run --project apps/api pytest tests/metrics/test_benchmark.py tests/metrics/test_scoring.py tests/metrics/test_platform_isolation.py -q
```

预期：`<5/5—9/≥10` 三档及所有隔离反例通过。
6. Commit: `feat: implement reproducible dynamic benchmarks`

## Task 4: 手动与 Excel/CSV 暂存导入

**Files:**
- Create: `apps/api/app/modules/imports/models.py`, `parsers/tabular.py`, `dedupe.py`, `service.py`, `router.py`
- Create: `apps/web/src/app/workspaces/[workspaceId]/imports/**`
- Test: `apps/api/tests/imports/test_tabular_preview.py`, `test_dedupe.py`, `test_confirm.py`
- Fixture: `apps/api/tests/fixtures/imports/*.csv`, `*.xlsx`

1. 测试表头映射、逐行错误、数值/百分比/时间格式、平台字段差异、重复作品、新快照追加、确认前零正式写入、事务失败整体回滚和重复确认幂等。
2. 去重优先键为平台+账号+作品链接/ID；无链接仅以发布时间+标题提示疑似重复，不自动合并。
3. UI 展示新增/更新/疑似重复/失败，支持逐行修正和“一键采用所有高置信度映射”，最终必须人工确认。
4. 运行 imports 测试与上传 E2E，预期坏行不阻塞预览、确认只写有效选中行。
5. Commit: `feat: add staged tabular imports with deduplication`

## Task 5: 截图识别暂存与人工确认

**Files:**
- Create: `apps/api/app/modules/imports/screenshot.py`, `ocr_adapters.py`
- Create: `apps/web/src/components/imports/screenshot-review.tsx`
- Test: `apps/api/tests/imports/test_screenshot_recognition.py`

1. 先用固定 Mock 图片与 Mock 视觉输出测试字段映射、置信度阈值、平台识别冲突、低置信度留空、人工修正和确认后写入。
2. 视觉输出 schema 只允许平台、内容标识、指标候选、区域坐标和置信度；原始模型文本不直接入正式表。
3. OCR/视觉任务异步执行；识别结果永远进入 staging；截图保留策略在确认后执行。
4. 运行测试，预期无模型配置时可用 Mock，真实适配器失败时原数据不损坏。
5. Commit: `feat: add reviewable screenshot metric recognition`

## Task 6: 仪表盘与条件图表 API/UI

**Files:**
- Create: `apps/api/app/modules/metrics/dashboard.py`, `dashboard_router.py`
- Create: `apps/web/src/app/workspaces/[workspaceId]/accounts/[accountId]/page.tsx`
- Create: `apps/web/src/components/charts/**`
- Test: `apps/api/tests/metrics/test_dashboard.py`, `apps/web/src/components/charts/charts.test.tsx`

1. 测试首屏只返回 4—6 个目标卡、趋势、候选/异常、下一步行动；只有数据条件满足才返回折线/漏斗/热力图配置；不同量纲禁止默认双轴混合。
2. API 返回可追溯 drill-down filter；前端每个图表点击进入对应内容列表。
3. 样本不足显示数据卡、实际样本数和解释，不渲染误导图表。
4. 运行组件和 API 测试；人工检查 1440px 与 390px 布局。
5. Commit: `feat: build evidence-led account dashboard`

## Task 7: 爆款候选、人工确认和素材库

**Files:**
- Create: `apps/api/app/modules/analysis/viral.py`, `viral_models.py`, `viral_router.py`
- Create: `apps/web/src/app/workspaces/[workspaceId]/viral-library/**`
- Test: `apps/api/tests/analysis/test_viral_candidates.py`

1. 测试只有可比较样本≥10、至少一维进入前 10% 且达到绝对门槛才推荐；候选按流量/互动/涨粉/转化分类；配置变化不改历史结论。
2. 进入素材库必须人工确认并添加策略标签、适用场景、结构摘要；撤销不删除历史审计。
3. 未确认候选不能被生成模块查询到。
4. Commit: `feat: add account-scoped confirmed viral library`

## Task 8: 有证据的 AI 深度分析

**Files:**
- Create: `apps/api/app/modules/analysis/features.py`, `schemas.py`, `service.py`, `tasks.py`, `router.py`
- Create: `apps/web/src/app/workspaces/[workspaceId]/contents/[contentId]/analysis/**`
- Test: `apps/api/tests/analysis/test_analysis_report.py`, `test_analysis_cache.py`

1. 测试报告 schema 必含数据表现、标题/文案/封面问题、证据、原因假设、置信度、建议和下一次实验；1 条快照不得产生趋势结论；样本不足必须降级；相同输入/版本命中缓存。
2. 先构造确定性 `AnalysisEvidenceBundle`，模型只能引用 bundle 中的 ID；输出引用不存在时整次结果标记失败，不保存为成功报告。
3. 支持手动触发和账号可选自动触发；保存模型/Prompt/算法/基准/快照版本。
4. UI 提供有用/无用、保存建议、采用状态；写入产品事件。
5. E2E：内容→快照→基准→分析→保存建议→爆款确认；预期完成一次闭环的前半段。
6. Commit: `feat: deliver evidence-grounded content analysis`

## Task 9: 模块验收

运行主计划 Gate A，并额外运行：

```bash
uv run --project apps/api pytest tests/metrics tests/imports tests/analysis -q
pnpm --filter e2e test metrics-import-analysis.spec.ts
```

人工验收抖音和小红书各一套数据，确认任何平台切换都不会复用另一平台的指标、基准或报告。Commit: `test: lock metrics import and analysis acceptance`
