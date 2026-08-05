# 运营智能体确定性验收

验证日期：2026-08-05。本报告只证明固定 Mock、人工合成数据和隔离环境中的工程边界，不代表真实模型效果、平台过审率或自动发布能力。

## 评估集

- Fixture：`tests/fixtures/operations_agent/cases.json`
- 版本：`operations-agent-eval-v1`
- 总样本：32
- 抖音：16，独立计算
- 小红书：16，独立计算
- 数据来源：全部人工合成，不含真实账号、正文、Prompt、Cookie、密钥或供应商响应

两个平台分别覆盖以下 16 组：正常闭环、数据不足、跨平台资源、未知工具注入、正文提示注入、Viewer 批准、陈旧批准、过期确认、请求前超时、请求后结果未知、Worker 租约丢失、重启恢复、高风险关闭、事实冲突关闭、Demo Mock 边界、无支付/发布能力。

## 固定门槛

`apps/api/tests/operations_agent/test_evaluation.py` 对每个平台单独执行以下门槛：

| 门槛 | 通过条件 |
| --- | --- |
| 主候选 | `CandidateKind` 必须是服务端已注册值 |
| 平台与账号 | 账号引用带平台前缀；执行器仍在调用前重验 workspace/platform/account |
| 工具目录 | 每个工具必须来自 `operations-agent-tools-v1`，未知工具被拒绝 |
| 参数 | 使用真实 Pydantic 工具输入合同验证，不补字段、不猜类型 |
| 权限 | 写操作前按真实角色权限矩阵判断；Viewer/Demo 拒绝 |
| 批准与确认 | 只接受 exact 绑定；陈旧、过期或不匹配统一拒绝 |
| 工具结果 | 每个工具提议必须有且只有一个结果或明确拒绝结果 |
| 重试 | 单次 Provider 最多 2 次；结果未知时不自动重试 |
| 隔离 | 跨工作区或跨平台访问始终为 false |
| 隐私 | 用例和结果不得含秘密或私有正文 |
| 能力边界 | 工具目录不得出现发布、支付、Cookie 或任意 SQL 工具 |
| 终态与证据 | 成功终态必须保留至少一条可核对 Evidence 引用 |

固定 Mock 结果是确定性的。真实 Provider 不参与普通 CI；只有用户另外授权 Provider、地域、能力、合成请求集和费用上限后，才能执行受控真实验收。

## 全链路与重启证据

`tests/e2e/operations-agent.spec.ts` 使用独立 Editor 完成：读取每日建议、生成并批准计划、服务器 Worker 执行九个受控步骤、查看风控摘要和固定免责声明。界面和工具目录均不提供发布或支付操作。

`scripts/verify-fresh-install.sh` 在隔离 Compose 中先运行完整 E2E，记录首个 Task 8 验收工作区的 workspace、run、step、confirmation、artifact、content ID 集合；随后执行正常 `down`（不删卷）和重启，在第二轮 E2E 前比较同一集合。当前工具目录没有 `protected_write`，因此 confirmation 集合为空；“空集合在重启前后保持为空”是当前真实合同，不伪造确认记录。

2026-08-05 最终结果：首次启动 5/5 E2E 通过，正常停机重启后再次 5/5 通过；重启前后的 workspace、run、9 个 step、artifact 和正式 content ID 集合完全一致。脚本结束后随机前缀容器、网络和卷均已清理。

## 诚实边界

- 真实千问：`not_run`；Catalog 继续为 `experimental`。
- 真实抖音/小红书页面：`not_run`。
- 自动发布：未实现；智能体只分析、生成草稿、风控复检、保存摘要和创建导出。
- 支付调用：未实现，工具目录和界面均无支付入口。
- macOS 本地便携运行：已在既有 Task 3 验收通过；Windows/Edge：`not_run`。
- 外部热点/趋势自动搜索：未实现。
- 独立非开发者智能体测试：`not_run`，原因 `independent_non_developer_agent_session_pending`。

## 复现命令

```bash
cd apps/api
.venv/bin/python -m pytest -q tests/operations_agent/test_evaluation.py
cd ../..
bash scripts/verify-fresh-install.sh
```

脚本只创建随机前缀的临时 Compose 项目，结束后删除该项目的容器、网络和卷，不连接既有持久化开发数据库。
