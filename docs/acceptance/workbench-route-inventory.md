# 工作台正式路由清单

验证日期：2026-07-30。这里的“可见”指左侧主导航可见；页面按钮仍受服务端 WorkspaceContext、角色、CSRF 和资源归属校验约束。自动化只使用合成数据和 Mock Provider。

| 页面 | 规范路由（位于 `/workspaces/{workspace_id}` 下） | 导航分组 | Admin | Editor | Viewer | 页面主操作 | 深链接 | 自动化证据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 工作台总览 | `/` | 工作台 | 是 | 是 | 是 | 执行当前最高优先级行动 | 完整 Shell、顶部范围与面包屑 | `workbench-navigation.spec.ts`、`workbench-visual.spec.ts` |
| 账号仪表盘 | `/accounts`；详情 `/accounts/{account_id}` | 内容运营 | 是 | 是 | 是 | 查看账号 | 账号详情从路径恢复真实账号范围 | `workbench-navigation.spec.ts`、`workbench-mobile.spec.ts` |
| 栏目与活动 | `/columns` | 内容运营 | 是 | 是 | 否 | 新建或编辑栏目覆盖 | platform/account Scope 可恢复 | `workbench-navigation.spec.ts`、`columns-center.test.tsx` |
| 内容库 | `/contents` | 内容运营 | 是 | 是 | 是 | 新建内容（Viewer 不显示） | 完整筛选、排序、分页可恢复 | `content-detail.spec.ts`、`content-list.test.tsx` |
| 数据导入 | `/imports` | 内容运营 | 是 | 是 | 否 | 选择一种导入来源 | platform/account Scope 可恢复 | `metrics-import-analysis.spec.ts`、`workbench-mobile.spec.ts` |
| 分析中心 | `/analysis` | 内容运营 | 是 | 是 | 是 | 打开单条分析 | returnTo 恢复队列筛选与分页 | `workbench-navigation.spec.ts`、`analysis-queue.test.tsx` |
| 爆款素材库 | `/viral-library` | 策略资产 | 是 | 是 | 是 | 人工确认候选（Viewer 不显示） | returnTo 恢复平台、账号和状态 | `full-loop.spec.ts`、`viral-library.test.tsx` |
| 账号风格 | `/styles`；详情 `/styles/{account_id}` | 策略资产 | 是 | 是 | 是 | 选择账号或维护样本（Viewer 只读） | 单账号 Scope，禁止全账号合并 | `full-loop.spec.ts`、`style-profile-center.test.tsx` |
| 事实资料 | `/facts` | 策略资产 | 是 | 是 | 是 | 添加/确认来源（Viewer 不显示） | 合法平台、账号范围可恢复 | `full-loop.spec.ts`、`fact-source-center.test.tsx` |
| 生成中心 | `/generation` | AI 创作 | 是 | 是 | 是 | 五步生成（Viewer 只读结果） | step/platform/account 可恢复 | `generation-workbench.spec.ts`、`generation-wizard.test.tsx` |
| 发布前检查 | `/preflight` | AI 创作 | 是 | 是 | 是 | 打开内容风控详情 | returnTo 恢复队列状态与分页 | `risk-rag.spec.ts`、`preflight-queue.test.tsx` |
| 风控知识库 | `/risk-knowledge` | 治理与数据 | 是 | 否 | 否 | 上传、审核或生效知识 | Admin 深链接；其他角色由服务端拒绝 | `risk-rag.spec.ts`、`workbench-navigation.spec.ts` |
| 导出与备份 | `/data-management/exports` | 治理与数据 | 是 | 是 | 否 | 创建导出或恢复预览 | 完整 Shell；服务端重验 workspace | `backup-restore.spec.ts`、`workbench-visual.spec.ts` |
| 回收站 | `/data-management/trash` | 治理与数据 | 是 | 否 | 否 | 恢复软删除内容 | Admin 深链接；与工作区删除分离 | `workbench-visual.spec.ts`、`export-api.test.ts` |
| 后台任务 | `/settings/jobs` | 工作区管理 | 是 | 是 | 否 | 查看任务状态；Editor 无重试/取消/补偿 | 完整 Shell，唯一 main landmark | `workbench-navigation.spec.ts`、`job-operations.test.tsx` |
| 工作区设置 | `/settings` | 工作区管理 | 是 | 否 | 否 | 管理成员、模型、安全与删除 | Admin 深链接；其他角色由服务端拒绝 | `workbench-navigation.spec.ts`、`workbench-mobile.spec.ts` |

角色矩阵固定为 Admin 16 项、Editor 13 项、Viewer 9 项。Demo 位于 `/demo`，没有私有 WorkspaceShell、主导航或写操作，只能通过明确链接进入 `/enter`。

## 兼容路由

| 旧地址 | 当前行为 | 安全约束 | 证据 |
| --- | --- | --- | --- |
| `/contents/{content_id}/analysis` | 重定向到 `/contents/{content_id}?tab=analysis` | 仅保留合法 platform/account 和当前 workspace 内 returnTo | `content-detail.spec.ts` |
| `/accounts/{account_id}/settings` | 重定向到规范单账号仪表盘 | 保留资源 ID 和合法 Scope；外部、跨 workspace 或嵌套 returnTo 被丢弃 | `workbench-navigation.spec.ts` |
| `/settings/members` | 在共享 Shell 内兼容渲染成员管理 | Admin 权限、CSRF 和 workspace 由服务端校验 | `workbench-navigation.spec.ts` |
| `/settings/models` | 在共享 Shell 内兼容渲染模型与预算管理 | 不回显密钥；Admin 权限由服务端校验 | `workbench-navigation.spec.ts` |

正式内容组件已改用五标签规范分析地址；兼容路由暂不删除。仓库中的 API 路径（例如 `/analysis-runs`）不是前端旧页面链接，不在此次重定向范围内。
