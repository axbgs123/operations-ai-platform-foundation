# 工作台自动化验收记录（2026-07-30，2026-08-01 两级导航复验）

## 结论与边界

- 验收基线：`274c163fcbbe1d6a4cee669927962cfcfa06e584`；Task 10 结果随提交 `test: accept modular operations workbench` 固化。
- 2026-08-01 在不改变路由、权限、API 和业务页面的前提下，将左侧导航复验为五个大类和一个当前小功能列表。
- 分支：`codex/workbench-redesign`。
- 自动化结论：正式路由、角色矩阵、Scope、移动端、视觉回归、Mock 全链路和发布门禁通过，可以准备独立非开发者 Task 9B 会话。
- 独立非开发者测试仍为 `not_run`，原因固定为 `independent_non_developer_session_pending`。
- 本次只使用人工合成数据、固定 Mock Provider 和隔离临时环境；未访问真实抖音/小红书页面，未调用真实千问或其他计费 API。
- 自动化证据不代表生产模型质量、平台过审率、Windows/Edge 兼容性或真实参与者可用性。

## 测试环境

- macOS，Chromium/Playwright，390px 与桌面固定视口。
- API/Web/Extension 使用当前工作树；Node 22、Python 3.12。
- PostgreSQL 使用 tmpfs 容器或每次创建并删除的临时 schema。
- Fresh-install、Redis、MinIO 和对象数据使用随机 Compose 项目、临时卷及自动清理。
- 视觉数据固定为 Task 10 合成工作区；动画关闭，随机 UUID 在截图前替换为固定占位值。
- 原持久化开发数据库、原 Docker 卷和真实私有运营数据未连接、迁移、stamp、重建或删除。

## 正式路由与角色矩阵

唯一正式清单见 [workbench-route-inventory.md](../workbench-route-inventory.md)。

- Admin：5 个大类、16/16 个小功能，可见治理、成员、模型、删除和恢复入口。
- Editor：5 个大类、13/13 个小功能；无成员/模型/工作区删除入口，后台任务无重试、取消或补偿按钮。
- Viewer：4 个大类、9/9 个小功能；不显示“管理”大类，无栏目、导入及其他写入口；邀请码写按钮不进入 DOM，直接调用成员邀请码 API 返回 403。
- Demo：位于 `/demo`，没有私有 WorkspaceShell 或私有主导航；只读合成数据，可明确进入 `/enter`。
- 跨工作区上下文直接访问返回 404；资源存在性不通过角色错误泄露。
- 16 个模块均从“大类 → 当前小功能列表”到达，路由高亮、三段面包屑、顶部 Scope 和唯一 `main` landmark 均有 E2E 证据。

兼容验证包括内容分析旧路由、账号设置旧路由、成员设置和模型设置。旧账号设置安全重定向至规范账号仪表盘，只保留合法平台、当前账号和当前工作区内部 `returnTo`。

## Scope 与返回上下文

- `platform` 只接受 `douyin`、`xiaohongshu` 或空值。
- `account` 必须属于当前工作区并匹配平台；`column` 必须属于当前账号。
- 平台或工作区变化会清理不兼容账号、栏目及引用。
- URL 保存合法筛选、排序和分页；刷新、深链接、前进和后退可恢复。
- 内容库、分析队列、Preflight、账号下钻和策略资产返回路径使用当前工作区内的相对 `returnTo`。
- 外部 URL、协议相对 URL、路径穿越、跨工作区路径、嵌套和编码绕过均不作为返回目标。
- 双平台数据在账号、队列、素材和指标层分别筛选；全账号页面不生成混合播放量、CTR、趋势或综合评分。

## 可见导航全链路

`full-loop.spec.ts` 在隔离 Compose 中通过可见页面导航覆盖：

`工作台 → 账号 → 栏目 → 导入 → 内容 → 分析 → 爆款 → 事实 → 风格 → 五步生成 → 发布前检查 → 保存草稿 → 导出/恢复`

流程使用合成数据、Mock 文本/图片/OCR/Embedding，不访问真实平台或模型。API 只用于可重复的合成前置数据和业务断言；模块之间的到达、范围选择、页面标题、步骤状态和下一步均由可见 UI 操作完成。

## 移动端与可访问性

- 390px 模态抽屉具备 `dialog`、`aria-modal`、焦点锁定、Escape 关闭、关闭后焦点恢复、页面跳转后关闭和背景不可交互。
- 工作台根页先显示大类，选择后才显示该类小功能；深链接直接打开所在大类，并提供“返回全部分类”，移动端不并排渲染两栏。
- 工作台、账号、内容、分析、Preflight、爆款、风格、事实、风控、导出、回收站和后台任务均保持关键状态及下一步可读。
- Excel 复杂映射、封面精细编辑、ZIP 恢复、复杂知识审核、模型密钥/预算和工作区删除均显示 `DesktopOnlyNotice`，没有静默隐藏。
- 页面无主操作不可达的横向溢出；导航不依赖 hover。
- Task 1 对比度测试证明白底普通 `--text-secondary` 文本不低于 4.5:1。
- 标签键盘、主内容跳转、ARIA live、图表文本替代、图片替代文本和 reduced-motion 由现有组件测试与 Task 10 E2E 共同覆盖。

## 视觉回归与逐张复检

Darwin 基线共 32 张，位于 `tests/e2e/workbench-visual.spec.ts-snapshots/`：

- 运营：工作台、账号列表、账号仪表盘、栏目、内容库、导入、分析队列。
- 内容详情：概览、快照、分析、风控、生成记录。
- 策略资产：爆款、风格、事实。
- 生成：范围、事实、引用、编辑、复核五步。
- 治理：Preflight、风控知识、导出、回收站、后台任务、工作区设置。
- 导航状态：264px 展开态覆盖全部正式页面，另含 80px 收起态、大类抽屉和资产小功能抽屉。
- 公共与移动：Demo、手机工作台、手机内容详情。

32/32 稳定比较通过。人工逐张检查结论：

- 桌面同时只出现五个大类和当前大类的小功能；当前大类、当前页面及收起/展开状态明确。
- 页面标题、状态、问题和下一步层级可辨；空状态、无证据和错误状态使用文字说明，不只依赖颜色。
- 抖音与小红书以独立账号/范围呈现，没有截图显示跨平台合并业务指标。
- 未发现标题、状态、主操作重叠、关键文字截断或不可访问横向溢出。
- 手机页面为单列轻量布局，风险、平台、账号和下一步可读；桌面专属能力有原因和继续方式。
- 回收站未配置保留策略时显示安全空值，不再把合法 404 渲染为红色页面错误。

## 完整验证结果

| 门禁 | 结果 |
| --- | --- |
| API 全量 pytest | `924 passed`，1 条上游弃用警告 |
| Web 全量 | `42 files / 177 tests passed` |
| Extension 全量 | `8 files / 39 tests passed` |
| 两级导航路由/移动/视觉/完整闭环复验 | `3 + 2 + 1 + 1` 测试通过；视觉测试包含 32 张基线 |
| 全部 E2E | 20 个唯一用例均在其规定隔离环境通过 |
| Fresh-install | 两轮各 `4/4 passed`，覆盖 fresh/full-loop/backup/demo 与重启持久性 |
| Content Detail / RiskRAG 专用 E2E | 各 `1/1 passed`，临时 schema 已删除 |
| Ruff / Mypy | 通过；Mypy 检查 161 个源文件 |
| ESLint / TypeScript / Web production build | 通过 |
| OpenAPI / 生成 TypeScript / 平台指标漂移 | 无漂移 |
| 空库迁移 | 从零升级到 `20260729_0033 (head)` |
| Alembic check / schema consistency | 通过，临时 schema 已删除 |
| 固定 Mock RiskRAG 评估 | 双平台 gate 通过；`ENGINEERING_REGRESSION_ONLY`，无网络 |
| Docker Compose config | 通过 |
| 当前树 / Git 历史秘密扫描 | 通过；Gitleaks 扫描 69 个提交、无发现 |
| pnpm / Python 生产依赖审计 | 无已知漏洞 |
| API / Web 最终镜像 Trivy | HIGH/CRITICAL 均为 0 |
| 源码与最终镜像 SPDX SBOM | 已生成并通过固定 `spdx-tools 0.8.3` 校验 |
| Extension Chrome/Edge 发布包 | 文件哈希一致，artifact/SBOM/秘密门禁通过 |
| `git diff --check` | 通过 |

全量 Playwright 不能把使用不同端口和独立 schema 的专用配置混在一个默认进程中运行；一次诊断性混跑因此触发端口、共享登录限流和环境假失败。各失败项随后都按仓库定义的专用配置和隔离环境重跑通过，未用跳过或放宽断言掩盖。

## Task 10 中关闭的问题

- Viewer 曾看到“栏目与活动”入口：增加角色矩阵失败测试后移除。
- 后台任务页面曾产生嵌套 `main`：改为共享 Shell 的唯一主 landmark。
- 旧账号设置仍使用深色独立页面：改为范围安全的规范路由重定向。
- 内容内部分析链接仍指向旧地址：改用五标签规范地址，保留兼容路由。
- 回收站的“未配置保留策略”404 被当作页面错误：只将该 404 解释为空配置，其余错误继续传播。
- Extension 轮询超时对象遗漏 OpenAPI 要求的 `platform` 和 `page_version`：先增加失败测试，再保留原采集范围。
- Foundation 与成员权限旧 E2E 断言不符合新标题层级和“无虚假写按钮”规则：改为唯一 H1/真实归属断言，并同时验证写按钮缺失与服务端 403。

## 最终代码复核

2026-08-01 两级导航改动已完成独立只读复核：

- `Critical: 0`
- `Important: 0`
- `Minor: 0`
- `Ready: Yes`

复核确认平台/账号 Scope 在桌面大类、小功能、面包屑和移动端链接间完整保留；根页与深链接两种手机抽屉流程均能正确管理焦点；Viewer/Editor 无权限深链安全降级；会话失效只清理导航命名空间，不误删其他浏览器存储。

## AC-01—AC-16 与真实验证边界

详见 [requirements-traceability.md](../requirements-traceability.md)：

- `passed`：8
- `partial`：7
- `blocked`：0
- `not_run`：1

必须保留的边界：

- 真实千问验收：`not_run`；Catalog 仍为 `experimental`。
- 真实抖音/小红书创作者页面：`not_run`。
- Windows/Chrome、Windows/Edge 及未实际执行的浏览器/系统组合：`not_run`。
- 独立非开发者测试：`not_run`，原因 `independent_non_developer_session_pending`。
- 自动联网检索未配置：`partial`。
- Facts 细粒度账号/栏目范围不存在：`partial`。
- 完整八阶段生命周期模型不足：`partial`。
- 文本生成与正式 `content_id` 关联不足：`partial`。
- `text-embedding-v4` 没有确认的日期快照。

## Task 9B 准备

- [非开发者测试指南](../non-developer-test-guide.md)
- [空白会话记录模板](../test-session-template.md)
- [独立参与者任务卡](../non-developer-participant-task-card.md)

参与者必须独立完成 11 项任务；主持人只提供 Editor 邀请码、开始计时并记录真实求助和卡点，不代替参与者操作。会话发生前不得填写参与者、耗时、成功率、评价或问题结论。

## 隔离环境启动与停止

- 完整 Fresh-install：仓库根目录执行 `bash scripts/verify-fresh-install.sh`。脚本使用随机 Compose project；退出时自动 `down --volumes --remove-orphans`。
- 常规 E2E：先准备独立临时 PostgreSQL/MinIO，再按对应 Playwright config 运行；Content Detail 与 RiskRAG 必须使用各自专用配置。
- 会话结束后核对并删除仅以 `operations_ai_task7_` 或 `operations-ai-task10-` 开头的临时资源。不得把原开发项目、原数据库或原 Docker 卷作为清理目标。
