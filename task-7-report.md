# Task 7 报告：隔离验收、确定性制品与 macOS Chrome 交接

日期：2026-08-10

分支：`codex/workbench-redesign`

目标提交信息：`test: accept persistent full-page extension capture`

## 结果

Task 7 已完成为可审计的 `partial` 验收：持久设备续签和真实扩展消息链自动化通过；Playwright 无法产生 Chrome 对 `captureVisibleTab` 所要求的真实用户手势，因此只把该截图取得段留给 macOS Chrome 人工验收，未伪造完整浏览器截图/上传链。确定性 Chrome/Edge 0.3.0 包已生成。

## RED 与修复

1. brief 给出的根目录命令 `pnpm exec playwright test -c tests/e2e/playwright.extension.config.ts` 首先失败：根 workspace 没有 Playwright 可执行文件；锁定依赖属于 `tests/e2e`。后续使用等价的正确命令 `pnpm --dir tests/e2e exec playwright test -c playwright.extension.config.ts`。
2. 正确 runner 首次在收集前失败，因为旧配置依赖固定的本机 PostgreSQL `:55432`。配置改为随机运行 ID、随机端口、专属 tmpfs PostgreSQL/Redis 容器和随机 schema/bucket。
3. E2E 随后在 Manifest 版本断言上真实 RED：构建仍为 `0.2.0`。Manifest、包元数据、构建元数据和客户端上报统一为 `0.3.0`。
4. 同一临时 profile 完整浏览器重启后续签真实 RED。证据显示 `storage.local` 注册和 IndexedDB 私钥完好，私钥仍不可导出且能签名/验签，`storage.session` 已清空。根因是原生 `fetch` 被作为依赖对象方法调用，Worker 抛出 `Illegal invocation`。新增 receiver 回归测试后，以局部函数引用调用原生 fetch；重启续签通过。
5. 真实 Popup 点击整页采集后，第一张截图安全失败。Worker 精确错误为缺少 `<all_urls>` 或用户手势授予的 `activeTab`；Manifest 已声明 `activeTab`，但 `chrome.action.openPopup()` 的程序化测试入口不产生用户手势。按照 brief，没有增加 `<all_urls>`、没有伪造 `captureVisibleTab`，只把这一段标为 `not_run`。

## 自动化证据

- 真实 unpacked Extension：固定扩展 ID、真实 action Popup、Service Worker、content script 和 Chrome storage/IndexedDB。
- 配对：一次性码通过真实 Popup 兑换 201；设备注册不含 bearer/配对码；成员数重启前后保持 2；配对码重放 401。
- 续签：同一 profile 关闭并重新启动 Chromium；session bearer 不持久化；原设备 ID 与不可导出 P-256 私钥保留；challenge/renew 后获得新 Mock binding。
- 捕获边界：真实 Popup 触发整页消息链；程序化入口因无 `activeTab` 用户手势安全失败；overlay 显示 Mock、默认“遮挡敏感信息：关”、0 张且没有上传按钮。
- 组件链：4000px 合成长页、1280×800 viewport 的位置为 `0/800/1600/2400/3200/3200`；6 张切片拼接为 1280×4000，状态“完整”；上传元数据合同继续覆盖 `capture_mode/full-page`、完整性、停止原因和切片数。
- 清理：E2E 仅按精确随机运行 ID 删除本轮 schema、容器和 profile。早期中断诊断遗留的本 worktree PID 64922/64929 已核对 cwd/端口后精确 TERM；未触碰任何既有 Compose 项目或卷。

## 确定性制品

固定 `SOURCE_DATE_EPOCH=1785744000` 连续执行两次 `pnpm --filter extension package`：

- 两次 unpacked 文件列表和逐文件 SHA-256 相同。
- 两次 Chrome/Edge ZIP SHA-256 相同。
- unpacked/ZIP 均为 11 个文件。
- Chrome：`apps/extension/release/operations-capture-extension-chrome-0.3.0.zip`
- Edge：`apps/extension/release/operations-capture-extension-edge-0.3.0.zip`
- 两者 SHA-256：`c3e44b78f67eecf227fa3dada949a31b8e1cb93b930e7ae5acefde15df338f31`
- 用户可加载目录：`apps/extension/release/unpacked`
- 离线验证：`release_artifact=clean`

包使用明确 allowlist，拒绝符号链接、source map、日志、远程脚本、动态代码、常见令牌/私钥、截图、测试/fixture、IndexedDB 数据和环境文件。

## 全仓门禁

通过：

- API：隔离随机 tmpfs PostgreSQL/Redis，`1089 passed`；Ruff `All checks passed!`；MyPy `Success: no issues found in 174 source files`。
- Web：54 个测试文件、330 个测试通过；lint/typecheck 通过。
- Extension：14 个测试文件、173 个测试通过；lint/typecheck 通过。
- Extension E2E：`1 passed`。
- `pnpm schemas:check`、`pnpm metrics:check`、`bash scripts/secret-scan.sh` 通过。
- 便携验收合同：12 个测试通过；`bash -n scripts/verify-portable-release.sh` 通过。
- 两次确定性打包与 `verify-artifact` 通过。

命令差异如实记录：brief 中的 `scripts/check-openapi-drift.sh`、`scripts/check-schema-consistency.sh`、`scripts/scan-secrets.sh` 在仓库不存在；实际同等门禁是 `pnpm schemas:check`、`pnpm metrics:check`、`scripts/secret-scan.sh`。没有添加假兼容脚本。全量 API 首次在没有依赖的环境中得到 1073 passed/9 failed/7 errors；注入隔离依赖后暴露并修正前序迁移遗留的 0035/0036 head 断言，最终全绿。

## 未执行边界

- 用户 macOS Chrome 安装/重载：`not_run`；本任务没有操作用户 Chrome。
- 真实工具栏点击或快捷键手势：`not_run`。
- `captureVisibleTab` 后的真实预览、Mock 上传、Web 人工确认和暂存对象删除：`not_run`，原因是上一项用户手势授权不可由 Playwright 程序化 Popup 产生。固定 6 屏、1280×4000 仅为合成夹具组件证据；真实页面应按实际高度自适应验收。
- 真实抖音/小红书页面：`not_run`，未获得额外授权。
- 真实付费 Provider：`not_run`，调用次数 0、费用 0。
- Edge/Windows 运行时：`not_run`；只生成了内容相同的确定性 Edge 包。
- 便携包完整 Compose 启动验收：`not_run`；本任务仅更新/测试 portable verifier 合同，没有启动或修改用户现有 Compose/卷。

人工步骤见 `docs/acceptance/extension-0.3.0-macos-chrome.md`。
