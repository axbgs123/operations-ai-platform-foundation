# 产品验收需求追溯矩阵

本矩阵对应设计文档第 25 节。自动化证据使用 Mock Provider、人工合成数据和隔离临时环境；它不替代独立非开发者验收。验证日期均为 2026-07-29。

## AC-01

- 原始需求文字：无邀请码访客可以安全体验示例工作区。
- 对应模块：公开 Demo、只读工作区、产品事件隔离。
- 精确自动测试：`apps/api/tests/demo/test_demo_isolation.py::test_public_demo_is_read_only_and_private_workspaces_are_hidden`；`tests/e2e/full-loop.spec.ts`，标题 `1-2 public Demo needs no invite and stays read-only`。
- 人工验收步骤：未登录打开 Demo，浏览示例内容并尝试修改；确认无需邀请码且修改被拒绝。
- 证据路径：`tests/e2e/full-loop.spec.ts`；`docs/acceptance/evidence/automated-task9-2026-07-29.md`。
- 当前结果：passed。
- 已知限制：独立非开发者尚未确认页面文案是否易懂；人工状态为 `not_run`，原因 `independent_non_developer_session_pending`。
- 最后验证日期：2026-07-29。
- 验证环境：macOS Docker Desktop，隔离 Compose，Chromium，Mock Provider。

## AC-02

- 原始需求文字：每名管理员、编辑者和查看者使用独立邀请码进入隔离的私有工作区，并可独立撤销和审计。
- 对应模块：WorkspaceContext、成员角色、邀请码、撤销与审计。
- 精确自动测试：`apps/api/tests/workspace/test_scope.py::test_cross_workspace_resources_return_not_found`；`apps/api/tests/workspace/test_membership.py::test_admin_can_issue_and_revoke_member_codes`；`tests/e2e/full-loop.spec.ts`，标题 `3-5 isolated private workspace and admin/editor/viewer roles`。
- 人工验收步骤：分别用三种角色邀请码登录，核对可见操作；撤销一个成员并再次访问。
- 证据路径：上述测试文件；自动化验收报告。
- 当前结果：passed。
- 已知限制：邀请码易用性尚未由独立非开发者测试；人工状态 `not_run`（`independent_non_developer_session_pending`）。
- 最后验证日期：2026-07-29。
- 验证环境：隔离 Compose/PostgreSQL，合成工作区。

## AC-03

- 原始需求文字：抖音和小红书可以分别创建账号、栏目和指标配置。
- 对应模块：账号、栏目、目标、平台指标注册表。
- 精确自动测试：`apps/api/tests/metrics/test_platform_isolation.py::test_platform_metric_definitions_cannot_be_mixed`；`tests/e2e/full-loop.spec.ts`，标题 `6-8 dual-platform account objectives and metric configuration stay separate`。
- 人工验收步骤：各创建一个平台账号，比较栏目、目标与指标选项，确认无跨平台字段。
- 证据路径：`apps/api/tests/metrics/test_platform_isolation.py`；`tests/e2e/full-loop.spec.ts`。
- 当前结果：passed。
- 已知限制：未连接真实平台账号。
- 最后验证日期：2026-07-29。
- 验证环境：隔离 Compose，合成抖音/小红书账号。

## AC-04

- 原始需求文字：手动、Excel、截图和运营数据采集扩展可以完成内容及快照导入。
- 对应模块：导入暂存、截图 Mock 识别、Capture Extension。
- 精确自动测试：`apps/api/tests/imports/test_import_api.py::test_xlsx_preview_and_confirm`；`apps/api/tests/imports/test_extension_capture.py::test_extension_capture_waits_for_web_confirmation`；`tests/e2e/full-loop.spec.ts`，标题 `9-11 manual, Excel, screenshot and Capture Extension fixture imports stay staged until confirmation`。
- 人工验收步骤：依次执行四种导入，修正识别字段后确认快照。
- 证据路径：`tests/e2e/full-loop.spec.ts`；`tests/e2e/extension-safe-capture.spec.ts`；`apps/extension/supported-pages.json`。
- 当前结果：partial。
- 已知限制：真实抖音/小红书页面尚未验证；Windows/Edge 真实环境尚未验证；Playwright 未加载真实扩展包访问真实创作者平台；只验证了脱敏 Fixture。
- 最后验证日期：2026-07-29。
- 验证环境：macOS、Chromium、脱敏静态 Fixture、Mock OCR。

## AC-05

- 原始需求文字：动态基准能按平台、账号、内容类型、数据成熟度和用户范围正确计算；缺少推荐快照时正确展示数据完整度。
- 对应模块：指标注册表、动态基准、成熟度与完整度。
- 精确自动测试：`apps/api/tests/metrics/test_benchmarks.py::test_benchmark_filters_platform_account_content_type_maturity_and_user_range`；`apps/api/tests/metrics/test_completeness.py::test_missing_recommended_snapshots_are_reported`；`tests/e2e/full-loop.spec.ts`，标题 `12-16 platform metrics, maturity, dashboard and grounded analysis do not overclaim`。
- 人工验收步骤：切换平台、内容类型和成熟度，核对样本数与缺失提示。
- 证据路径：上述指标测试与全链路 E2E。
- 当前结果：passed。
- 已知限制：动态基准只使用人工合成样本，不代表生产分布。
- 最后验证日期：2026-07-29。
- 验证环境：隔离 PostgreSQL，固定合成指标。

## AC-06

- 原始需求文字：仪表盘按“状态—问题—原因—行动”展示，并仅在数据条件满足时显示对应图表。
- 对应模块：仪表盘、分析报告、图表门禁。
- 精确自动测试：`apps/web/src/components/dashboard/dashboard.test.tsx`；`apps/api/tests/analysis/test_report_contract.py::test_report_uses_status_problem_reason_action_contract`；全链路 E2E 步骤 12—16。
- 人工验收步骤：由独立非开发者查看完整与不完整两种数据，说明四段含义并核对图表是否误显示。
- 证据路径：Web 组件测试；`docs/acceptance/test-session-template.md`。
- 当前结果：not_run。
- 已知限制：自动合同测试通过，但“普通人能否理解”尚无独立证据；原因 `independent_non_developer_session_pending`。
- 最后验证日期：2026-07-29。
- 验证环境：自动部分为 jsdom/隔离 Compose；人工环境未运行。

## AC-07

- 原始需求文字：AI 分析引用实际数据，样本不足时正确降级。
- 对应模块：Evidence Bundle、分析器、样本降级。
- 精确自动测试：`apps/api/tests/analysis/test_evidence.py::test_analysis_only_cites_supplied_evidence`；`apps/api/tests/analysis/test_degradation.py::test_small_sample_omits_trend_conclusion`；全链路 E2E 步骤 12—16。
- 人工验收步骤：打开引用并与导入快照逐项核对；用单样本确认降级提示。
- 证据路径：分析专项测试；全链路 E2E。
- 当前结果：partial。
- 已知限制：真实千问 API 尚未运行；Catalog 仍为 experimental；Mock 结果不代表真实千问效果。
- 最后验证日期：2026-07-29。
- 验证环境：固定 Mock Provider、合成 Evidence。

## AC-08

- 原始需求文字：风控 RAG 能返回当前平台有效规则、来源和修改建议，并通过来源等级、审核状态和评估集检查。
- 对应模块：RiskRAG 生命周期、隔离检索、引用验证、评估。
- 精确自动测试：`apps/api/tests/risk_rag/test_retrieval.py::test_metadata_filter_is_applied_before_vector_ranking`；`apps/api/tests/risk_rag/test_citations.py::test_citation_must_belong_to_current_evidence_bundle`；`apps/api/tests/risk_rag/test_evaluation.py::test_platform_metrics_are_reported_separately`。
- 人工验收步骤：分别扫描两平台合成文案，查看来源等级、状态、引用和建议。
- 证据路径：`apps/api/tests/risk_rag/`；`docs/architecture/risk-rag-evaluation-gates.md`。
- 当前结果：partial。
- 已知限制：固定合成评估只是工程回归门槛；当前不代表生产平台过审准确率；未打包未经授权规则原文。
- 最后验证日期：2026-07-29。
- 验证环境：Mock Embedding/固定合成评估集。

## AC-09

- 原始需求文字：账号风格默认继承，并可按标题、文案、封面分别关闭。
- 对应模块：风格样本、版本化画像、三项继承开关。
- 精确自动测试：`apps/api/tests/style_facts/test_style_inheritance.py::test_disabling_each_inheritance_switch_removes_that_history_from_context`；全链路 E2E 步骤 19—23。
- 人工验收步骤：逐一关闭标题、文案、封面继承，比较生成上下文。
- 证据路径：风格继承专项测试；全链路 E2E。
- 当前结果：passed。
- 已知限制：风格样本为合成内容。
- 最后验证日期：2026-07-29。
- 验证环境：隔离数据库、Mock Provider。

## AC-10

- 原始需求文字：上传资料后必须确认事实清单；系统正确执行 L1—L5 来源等级和冲突规则，生成结果不能添加未确认或禁止视觉推测的参数。
- 对应模块：事实来源、确认、冲突与生成事实门禁。
- 精确自动测试：`apps/api/tests/style_facts/test_conflicts.py::test_source_priority_and_explicit_override_resolve_conflict`；`apps/api/tests/style_facts/test_visual_prohibitions.py::test_l5_prohibited_field_cannot_cross_the_confirmation_boundary`；`apps/api/tests/generation/test_text_generation.py::test_high_risk_fact_conflict_blocks_generated_output`。
- 人工验收步骤：上传 L1—L5 合成资料，制造冲突并确认；尝试加入未确认视觉参数。
- 证据路径：Style/Facts 与 Generation 专项测试；全链路 E2E 步骤 19—25。
- 当前结果：passed。
- 已知限制：不含真实私有资料。
- 最后验证日期：2026-07-29。
- 验证环境：合成事实资料、Mock Provider。

## AC-11

- 原始需求文字：爆款内容只有人工确认后才能进入素材库并被引用。
- 对应模块：爆款候选、人工确认、生成素材库。
- 精确自动测试：`apps/api/tests/analysis/test_viral.py::test_unconfirmed_candidate_is_not_generation_eligible`；全链路 E2E 标题 `17-18 only a manually confirmed viral item enters the generation library`。
- 人工验收步骤：比较确认前后素材库和生成引用。
- 证据路径：爆款专项测试；全链路 E2E。
- 当前结果：passed。
- 已知限制：爆款阈值只用合成指标验证。
- 最后验证日期：2026-07-29。
- 验证环境：隔离数据库、合成快照。

## AC-12

- 原始需求文字：标题、文案和四种封面模式可以完成生成和保存。
- 对应模块：文本生成、封面 template/ai_visual/hybrid/custom、OCR/RiskRAG 门禁。
- 精确自动测试：`apps/api/tests/generation/test_text_generation.py::test_mock_contract_returns_titles_copy_and_structured_citations`；`apps/api/tests/generation/test_cover_modes.py::test_each_cover_mode_builds_expected_plan`；全链路 E2E 步骤 24—30。
- 人工验收步骤：普通用户完成文本生成、保存草稿并依次运行四种封面模式。
- 证据路径：Generation 专项测试；全链路 E2E。
- 当前结果：not_run。
- 已知限制：自动 Mock 全链路通过，但独立非开发者尚未完成保存流程；真实千问 API 尚未运行；原因 `independent_non_developer_session_pending`。
- 最后验证日期：2026-07-29。
- 验证环境：自动部分为隔离 Compose/Mock 图片模型；人工环境未运行。

## AC-13

- 原始需求文字：CSV、Markdown和JSON轻量导出可用；完整 ZIP 可以在校验后恢复结构化数据、媒体和原始知识文档。
- 对应模块：异步导出、完整 ZIP、校验和、恢复预览/确认。
- 精确自动测试：`apps/api/tests/exports/test_csv.py::test_csv_export_is_deterministic_and_formula_safe`；`apps/api/tests/exports/test_markdown.py::test_markdown_report_marks_missing_evidence`；`apps/api/tests/exports/test_json_restore.py::test_restore_preview_is_deterministic`；`tests/e2e/backup-restore.spec.ts`。
- 人工验收步骤：下载四类导出，打开可移植格式；恢复 ZIP 到新工作区并抽查媒体与知识来源。
- 证据路径：Exports 专项测试；`tests/e2e/backup-restore.spec.ts`。
- 当前结果：passed。
- 已知限制：恢复后的模型密钥与向量按设计不继承；需重新配置并重建索引。
- 最后验证日期：2026-07-29。
- 验证环境：隔离 PostgreSQL/MinIO，合成授权媒体和知识文档。

## AC-14

- 原始需求文字：AI 或识别任务失败时不破坏已保存数据。
- 对应模块：异步任务状态、事务回滚、补偿与暂存确认。
- 精确自动测试：`apps/api/tests/exports/test_zip_restore_failures.py::test_object_move_failure_rolls_back_and_registers_compensation`；`apps/api/tests/generation/test_generation_cache.py::test_failed_generation_does_not_overwrite_success`；`apps/api/tests/imports/test_extension_capture.py::test_failed_capture_never_writes_formal_snapshot`。
- 人工验收步骤：在合成测试环境触发失败，刷新已保存内容与快照。
- 证据路径：故障注入专项测试；备份恢复 E2E。
- 当前结果：passed。
- 已知限制：Task 4 旧 Embedding generation 尚未受控清理；旧生成对象清理留给既定保留策略。
- 最后验证日期：2026-07-29。
- 验证环境：SQLite/PostgreSQL 故障注入与隔离对象存储。

## AC-15

- 原始需求文字：项目可以依据文档在新环境中完成部署，仓库不包含秘密与真实私有数据。
- 对应模块：Compose、迁移、Demo seed、发布 allowlist、秘密扫描、SBOM。
- 精确自动测试：`apps/api/tests/open_source/test_release_security.py::test_release_tree_excludes_secret_and_private_patterns`；`tests/e2e/fresh-install.spec.ts`；`scripts/verify-fresh-install.sh`。
- 人工验收步骤：在一台未参与开发的新机器按 README 部署并记录所有阻塞。
- 证据路径：自动化验收报告；`docs/open-source/release-checklist.md`。
- 当前结果：partial。
- 已知限制：已在隔离无卷/无应用缓存环境通过，但没有真正独立的新机器；不得表述为独立机器验证通过。
- 最后验证日期：2026-07-29。
- 验证环境：macOS Docker Desktop、唯一 Compose 项目和临时卷。

## AC-16

- 原始需求文字：系统记录首次分析耗时、采集耗时、分析反馈、生成采用状态和每周有效运营闭环数。
- 对应模块：产品事件、北极星指标、Mock 污染隔离。
- 精确自动测试：`apps/api/tests/analytics/test_effective_loops.py::test_product_metrics_and_effective_loops_are_workspace_scoped`；`apps/api/tests/analytics/test_events.py::test_mock_events_are_not_analytics_eligible`；全链路 E2E 步骤 31—35。
- 人工验收步骤：独立测试者记录真实开始/结束、首次分析与采集耗时，并完成反馈、建议和下一条草稿。
- 证据路径：Analytics 专项测试；`docs/acceptance/test-session-template.md`。
- 当前结果：not_run。
- 已知限制：Mock 事件按设计不进入正式指标；真实非开发者耗时不得虚构，原因 `independent_non_developer_session_pending`。
- 最后验证日期：2026-07-29。
- 验证环境：自动合同在隔离 Compose 通过；真实参与者环境未运行。

## 跨项限制与状态汇总

- passed：9；partial：4；blocked：0；not_run：3。
- 非开发者测试：`not_run`；原因：`independent_non_developer_session_pending`。
- 真实千问 API 尚未运行，Catalog 仍为 `experimental`。
- `text-embedding-v4 没有确认的日期快照`，因此不得声称固定日期模型可重复。
- 真实抖音/小红书页面尚未验证；Windows/Edge 真实环境尚未验证；Playwright 未加载真实扩展包访问真实创作者平台。
- Task 4 旧 Embedding generation 尚未受控清理。
- 当前不代表生产平台过审准确率，也不代表产品正式发布。
