# 浏览器采集助手 0.3.0：macOS Chrome 验收与交接

## 当前结论

状态：`partial`

自动化已证明 0.3.0 的持久设备续签、真实 Popup/Service Worker/content-script 消息边界、Mock Provider 披露、默认关闭遮挡和确定性制品。自动化没有产生 Chrome 所要求的真实用户工具栏或快捷键手势，因此 `captureVisibleTab`、其后的真实 6 屏预览/上传/Web 人工确认仅保持 `not_run`；不得把组件测试写成完整浏览器链通过。

## 自动化证据

| 验收项 | 结果 | 证据边界 |
| --- | --- | --- |
| 版本与固定扩展 ID | `passed` | unpacked Manifest 为 `0.3.0`；隔离 Chromium 加载固定 ID `mdbmlilohlhmjmcmkpbpjhldganompcl` |
| Popup 配对 | `passed` | 通过真实 `chrome.action` Popup 输入一次性码；服务端返回 201；成员仍为原来的 2 人 |
| 设备续签 | `passed` | 关闭并用同一临时 profile 重启浏览器；`storage.session` 不复用 bearer，`storage.local` 注册与 IndexedDB 不可导出 P-256 私钥保留；新 Worker 完成 challenge/renew 并取得新 Mock binding |
| 配对码重放 | `passed` | 第二次兑换返回通用 401 |
| 快捷键分配显示 | `passed_display_only` | Popup 从 `chrome.commands.getAll()` 显示已分配快捷键；实际按键手势为 `not_run` |
| 遮挡默认值 | `passed` | 真实 content overlay 显示“遮挡敏感信息：关”；组件测试也验证 6 屏预览仍默认关闭 |
| 整页滚动与拼接 | `component_tested` | 固定 4000px 合成页、1280×800 viewport 产生滚动位置 `0/800/1600/2400/3200/3200`，6 张切片拼接为 1280×4000，状态“完整” |
| `captureVisibleTab` | `not_run` | Playwright 程序化打开 Popup 不产生 Chrome `activeTab` 用户手势授权；真实链确认安全失败、0 张且没有“确认上传”按钮 |
| Mock 上传与 Web 人工确认 | `not_run` | 依赖上一项真实截图；API/上传/确认合同由既有单元与集成测试覆盖，本次不声称浏览器全链执行 |
| 隔离与清理 | `passed` | 每次使用随机 PostgreSQL schema、专属 tmpfs PostgreSQL/Redis 容器、随机 S3 bucket 名和临时浏览器 profile；仅按精确运行 ID 清理，结束后均不存在 |

没有访问真实抖音或小红书数据，没有调用付费 Provider，没有保存配对码、bearer、Cookie、截图、IndexedDB 或测试数据到制品。

## 确定性制品

使用 `SOURCE_DATE_EPOCH=1785744000` 分别在 `TZ=UTC` 与 `TZ=Asia/Shanghai` 构建；两次 unpacked 文件列表、逐文件 SHA-256 和 ZIP SHA-256 完全相同。ZIP entry 使用固定 UTC DOS 时间、Unix creator、`0100644` mode、STORE compression 和排序顺序。Chrome 与 Edge 当前业务内容相同：

- `apps/extension/release/unpacked`：11 个文件，可直接由用户加载。
- `apps/extension/release/operations-capture-extension-chrome-0.3.0.zip`
- `apps/extension/release/operations-capture-extension-edge-0.3.0.zip`
- 两个 ZIP 的 SHA-256：`f5a11e2ee2e597c580b9591b908c38a248b77f96c245770c88fbb61284f20cf1`

制品使用根文件 allowlist 和 `assets/*.js` allowlist；拒绝符号链接、source map、日志、远程脚本、`eval`/`new Function`、常见令牌/私钥、截图、测试目录、fixture、IndexedDB 数据和环境文件。离线制品验证结果为 `release_artifact=clean`。

## 由用户执行的 macOS Chrome 清单

以下全部为 `not_run`，本次自动化没有操作用户 Chrome：

1. 打开 `chrome://extensions`，保留所有无关扩展；开启开发者模式。
2. 若同一路径的旧版已存在，只点击“重新加载”；否则只移除旧“运营数据采集助手”，再加载 `apps/extension/release/unpacked`。
3. 核对名称、版本 `0.3.0` 和权限：`activeTab`、`scripting`、`storage`；不得出现 `<all_urls>` 常驻权限。
4. 打开受支持的合成/已授权页面，从真实工具栏 Popup 核对快捷键显示、Mock Provider 和“遮挡敏感信息：关”。
5. 实际按一次已显示的整页快捷键；确认预览的“采集 N 屏”中 N 大于 0，完整性与当前页面实际可滚动范围一致，预览尺寸与当前页面一致，并在上传前保持人工确认。固定的“采集 6 屏”和 1280×4000 只属于上方 4000px 合成夹具的组件证据，不是任意真实页面的固定期望值。
6. 关闭并重新打开 Chrome，确认不重新输入配对码即可续签，且成员没有增加。
7. 完成一次 Mock 上传和 Web 人工确认；确认暂存对象随后删除。再分别检查可见区、选区和取消/失败降级。
8. 只删除本次创建的合成记录和临时资源，不清理无关扩展、Compose 项目或卷。

真实创作者页面必须另获明确授权；真实抖音/小红书、真实付费 Provider、Windows、Edge 运行时当前均为 `not_run`。

## 复现命令

```bash
pnpm --filter extension test
pnpm --dir tests/e2e exec playwright test -c playwright.extension.config.ts
SOURCE_DATE_EPOCH=1785744000 pnpm --filter extension package
apps/api/.venv/bin/python scripts/release-security.py verify-artifact --kind extension --path apps/extension/release/unpacked
```
