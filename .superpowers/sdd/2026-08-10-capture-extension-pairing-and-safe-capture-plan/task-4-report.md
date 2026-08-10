# Task 4 — Capture Extension 0.2 Popup 配对与页面就绪

## 状态

已完成。扩展升级为 `0.2.0`：Popup 使用 Web 端连接码配对，默认本机 API 为 `http://127.0.0.1:51201`，远程地址收在“高级设置”中并由现有 origin 校验限制为 HTTPS（本机 loopback 例外）。未接入真实截图流程。

## 提交

`feat: pair capture extension with current members`

## RED / GREEN

- RED：新增/更新 Popup 配对、auth、URL-only 页面识别和版本/Manifest 测试后，确认旧实现因缺少 `pairExtension`、Popup 的 Chrome 全局依赖、旧 fixture 判定及 `0.1.0` 版本而失败。
- GREEN：配对请求改为 `POST /v1/extension/pair`；连接码在 auth 与 Popup 的 `finally` 中清空且不写入存储；session binding 仅保留规定字段；页面支持仅由 hostname/path 决定；Popup 分别呈现未连接（含过期降级）、已连接不支持页、已连接支持页三种状态。

## 全量验证

- `pnpm --filter extension test` — 9 files / 46 tests passed
- `pnpm --filter extension lint` — passed
- `pnpm --filter extension typecheck` — passed
- `pnpm --filter extension build:chrome` — passed

## 自检

- Manifest 仍只使用 `activeTab`、`scripting`、`storage`；两个 creator host pattern 和 optional host permission 均未扩大。
- Popup 仅披露 Web 地址、工作区名称和成员显示名，不显示 token、workspace UUID 或 member UUID。
- 运行时页面识别不读取 fixture DOM 元数据，且不会将 capture region 或敏感区域假定为已验证。
- `GET_PAGE_STATUS` 与 `START_SAFE_CAPTURE` 消息均由 Popup 发出；本任务未连接真正截图动作。

## 担忧

内容脚本目前还没有处理这两条消息；Popup 在消息未就绪时安全降级为 URL-only 页面状态，真实安全采集接线留给 Task 5。

## 修复轮 1

- I1：在存储和配对响应的唯一边界添加运行时 binding 解析。它精确要求九个字段、拒绝额外 secret 字段，校验并规范化 server origin、校验 HTTPS web origin、workspace UUID、provider union 和可解析的到期时间。损坏 session 数据会删除；坏的 2xx 响应绝不写入存储。
- I2：远程 `DELETE` 的非 2xx 也被视为失败，但无论网络、CORS/权限错误还是 204，`revokeExtension` 都清除 session；Popup 在 `finally` 清理持久 trust、重渲染为未连接，并只显示安全的通用提示。
- I3：origin 规范化移动到 `pairExtension` 的 `try/finally` 内，所有失败出口均恰好清空一次连接码。
- M1：已连接状态隐藏并收起高级设置。
- M2：留待 Task 6 的真实 HTML/Chrome 集成验收。

修复轮验证：`pnpm --filter extension test`（9 files / 65 tests）、`lint`、`typecheck`、`build:chrome` 与 `git diff --check` 均通过。

## 修复轮 2

- NI1：`webOrigin` 复用与 server origin 完全相同的安全规则：HTTPS 或精确 loopback HTTP，且仍拒绝凭据、fragment、path/query 与混淆 hostname。真实默认 API 返回的 `http://localhost:3000` 现在可完成配对；外部 HTTP 继续被拒绝。
- NI2：撤销通知失败的提示改为“本地已解绑，但未能通知服务器；服务端令牌将在到期后自动失效。”，不会再承诺未实现的自动重试。

修复轮验证：`pnpm --filter extension test`（9 files / 65 tests）、`lint`、`typecheck`、`build:chrome` 与 `git diff --check` 均通过。
