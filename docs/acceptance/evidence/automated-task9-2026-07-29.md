# Task 9A 自动化验收证据

> 本报告只证明 Task 9A 自动化验收与非开发者测试准备，不代表 Task 9、真实模型、真实平台兼容或独立非开发者验收完成。

## 环境与边界

- 日期：2026-07-29
- 基线提交：`04a69143e7c7c6db4fda3c97a2b69f91b9323952`
- 分支：`codex/backup-open-source`
- 环境：macOS、Docker Desktop、Chromium、Node/pnpm、Python 3.12/uv
- 数据：人工合成 AI 科技账号、脱敏 Fixture、Mock Provider
- 数据库与对象存储：唯一临时 Compose 项目、临时卷或 pgvector tmpfs；验证后清理
- 未访问真实抖音/小红书页面，未调用真实千问 API，未使用真实密钥，费用为零
- 原持久化开发数据库和原 Docker 卷未迁移、未 stamp、未重建、未删除

## Gate A

| 检查 | 结果 | 数量/说明 |
| --- | --- | --- |
| API 全量 pytest | passed | 905/905 |
| API Ruff | passed | `ruff check apps/api/app apps/api/tests` |
| API Mypy | passed | 157 个源文件 |
| Web 测试 | passed | 25 个文件，51/51 |
| Web ESLint | passed | 退出码 0 |
| Web TypeScript | passed | 退出码 0 |
| Extension 测试 | passed | 8 个文件，38/38 |
| Extension ESLint/TypeScript | passed | 退出码 0 |
| Docker Compose config | passed | `docker compose -f infra/docker/compose.yml config --quiet` |

API 全量测试在独立 `pgvector/pgvector:0.8.2-pg18-trixie` tmpfs 容器运行。另有模型、生成、分析、RiskRAG、导出、删除和产品指标专项回归 587/587 通过。

## Gate B

| 检查 | 结果 | 数量/说明 |
| --- | --- | --- |
| 无卷 fresh install | passed | 唯一 Compose 项目从空卷构建、迁移、种子和启动 |
| fresh-install/full-loop/backup-restore | passed | 首次 3/3，保留同一临时卷重启后再次 3/3 |
| 全部 E2E | passed | 14/14；逐测试重置临时认证限流状态，不放宽生产限流 |
| `full-loop.spec.ts` | passed | 1/1，双 workspace、双平台、Mock 全闭环 |
| `backup-restore.spec.ts` | passed | 1/1，校验和、恢复、篡改拒绝、补偿与幂等 |
| Extension 安全采集 E2E | passed | 1/1，脱敏静态页面，不是真实扩展平台验证 |
| 模型配置 E2E | passed | 1/1，真实验收结果保持 `not_run` |
| 重启持久化 | passed | 临时 PostgreSQL/Redis/MinIO 数据在 stop/up 后保持 |
| 清理 | passed | 临时 Compose 项目、卷、tmpfs 容器和对象前缀已清理 |

一次将 14 条 E2E 放在同一进程连续执行时，测试共享 IP 正确触发邀请码认证限流；最终验收按测试用例隔离认证桶运行，业务数据库仍保持隔离环境内连续，以同时验证跨流程兼容性。

## Gate C

| 检查 | 结果 | 数量/说明 |
| --- | --- | --- |
| `pytest -m security` | passed | 83 passed，822 deselected |
| `pytest -m isolation` | passed | 22 passed，883 deselected |
| Node 生产依赖审计 | passed | `pnpm audit --prod --audit-level high`：无已知漏洞 |
| Python 生产依赖审计 | partial | `uv audit --no-dev --frozen` 无法连接 OSV：TLS handshake EOF |
| 当前树密钥扫描 | passed | `secret_scan=clean` |
| Git 历史密钥扫描 | passed | `secret_scan=clean` |
| OpenAPI 生成一致性 | passed | 重新生成前后文件 SHA-256 不变 |
| 平台指标类型漂移 | passed | `pnpm metrics:check` |

Python 审计的外部服务不可用不记为通过；需要在网络可正常访问 `api.osv.dev` 的受控 CI 或发布环境重跑。

## Gate D 自动部分

| 检查 | 结果 | 说明 |
| --- | --- | --- |
| 空库迁移 | passed | 从零升级至 `20260729_0033` |
| Alembic check | passed | `No new upgrade operations detected` |
| schema consistency | passed | head 与必需表一致；head 缺表反例会失败 |
| Mock Demo/私有闭环 | passed | 合成数据、只读 Demo、私有 workspace 隔离 |
| API/Web 非 root | passed | API `appuser`，Web `nextjs` |
| API/Web 只读运行配置 | passed | Compose `read_only`、tmpfs、cap_drop |
| 源码发布 allowlist | passed | 只对 Git 源码暂存目录验证；仓库根目录不是发布物 |
| README/文档链接 | passed | 本地链接、PNG 结构和 Compose 命令通过 |
| 锁文件 SPDX | passed | 项目结构门通过 |
| 镜像 SPDX 生成 | partial | Syft 成功生成并可解析为 JSON；固定 `pyspdxtools` 因 PyPI TLS 失败未执行 |
| API/Web Trivy | passed | High/Critical 均为 0 |
| Chrome/Edge 发布包 | passed | allowlist、CSP、SBOM、敏感信息检查通过 |
| 独立新机器 | not_run | 仅证明隔离无卷/无应用缓存环境，不推断独立机器 |

SBOM SHA-256：

- API 锁文件 SBOM：`9073a2d944ae3b30967393e6bd2bf2d9f48be52c41904553c2f3a4dbee3e1f9e`
- Web 锁文件 SBOM：`d3384c098ce5ee3b31f4d8becdf4fee41aa2c2e4520f82df726862ebc4ee4568`
- API 镜像 Syft SBOM：`92781f39ccaf4e3760b31ac591f57f1f1eaf468817291bb8dfa41ad5a68ce78b`
- Web 镜像 Syft SBOM：`7c017d26cb4d7853ed2221f8593abf60db47bf0fca931c39f3622e363be4ac4c`

扩展发布包：

- Chrome：`apps/extension/release/operations-capture-extension-chrome-0.1.0.zip`
- Edge：`apps/extension/release/operations-capture-extension-edge-0.1.0.zip`
- 两包 SHA-256：`f756af2815fe282224377a9d551a226d88df3f1e56ec014f09c404ddf31e59fe`

## 固定 Mock 风控评估

抖音和小红书分别使用 11 个合成样本，两个平台均通过工程回归门：

- 高风险召回率：1.0（4/4）
- 安全内容误报率：0.0（0/1）
- 引用正确率：1.0（7/7）
- 无依据结论比例：0.0（0/10）
- 严重度正确率：1.0（11/11）
- OCR 低置信度降级正确率：1.0（1/1）
- 两次固定 Mock 一致性：1.0（2/2）

标识为 `ENGINEERING_REGRESSION_ONLY`，`production_quality_claim_allowed=false`，不代表生产平台过审准确率。

## 追溯状态和人工边界

- AC-01—AC-16：passed 9、partial 4、blocked 0、not_run 3
- 非开发者测试：`not_run`
- 原因：`independent_non_developer_session_pending`
- 真实千问验收：`not_run`
- Catalog：`experimental`
- `text-embedding-v4` 没有确认的日期快照
- Task 4 旧 Embedding generation 尚未受控清理
- 真实平台页面、Windows/Edge、真实扩展包进入创作者平台均未验证

大型日志、Playwright trace、视频和临时截图未提交仓库；成功运行的临时诊断目录已清理。Task 9 尚未完成，下一步是 Task 9B 的真实独立非开发者测试与最终验收。
