# Task 7 报告：持久设备整页采集验收、确定性制品与 macOS Chrome 交接

日期：2026-08-10

分支：`codex/workbench-redesign`

任务提交：`6456f5116a1cb58c8f329ad618b790d10d0943cf`
提交信息：`test: accept persistent full-page extension capture`

## 结论

Task 7 完成为可审计的 `partial` 验收。自动化真实执行了 unpacked Extension 的 Popup、Service Worker、content script、设备注册、浏览器完整重启和持久设备续签；4000px 合成长页的滚动、6 张切片和 1280×4000 拼接由组件测试精确覆盖。

Playwright 通过 `chrome.action.openPopup()` 程序化打开 Popup 时，不会取得 Chrome 要求的 `activeTab` 真实用户手势授权。因此 `captureVisibleTab` 及其下游真实预览、Mock 上传、Web 人工确认和暂存对象删除保持 `not_run`。没有通过增加 `<all_urls>`、伪造截图或把组件测试冒充浏览器全链来绕过该边界。

Chrome/Edge 0.3.0 确定性制品已在本地生成并通过离线安全检查；没有 push、merge 或发布 Release，也没有操作用户 Chrome、真实创作者数据或付费 Provider。

## RED 演进、根因与修复

1. brief 中的根目录命令 `pnpm exec playwright test -c tests/e2e/playwright.extension.config.ts` 首先失败，因为根 workspace 没有 Playwright 可执行文件。Playwright 1.61.1 锁定在 `tests/e2e`，实际有效命令为：

   ```bash
   pnpm --dir tests/e2e exec playwright test -c playwright.extension.config.ts
   ```

2. 正确 runner 首次在测试收集前失败，因为旧 E2E 固定依赖本机 PostgreSQL `:55432`。E2E 改为每轮随机 12 位 run ID、随机端口、专属 tmpfs PostgreSQL/Redis 容器、随机 PostgreSQL schema、随机对象存储 bucket 前缀和临时浏览器 profile。清理只接受与该 run ID 精确匹配的资源名。

3. E2E 随后在版本断言上真实 RED：构建产物仍为 `0.2.0`。Manifest、Extension package、构建元数据、客户端上报和相关断言统一升级至 `0.3.0`。

4. 使用同一临时 profile 关闭并重新启动整个 Chromium 后，设备续签真实 RED。检查证明：

   - `chrome.storage.session` 中的 bearer 已消失；
   - `chrome.storage.local` 中原设备注册仍存在；
   - IndexedDB 中 P-256 私钥仍不可导出，并可继续签名/验签；
   - 新 Service Worker 健康，但续签请求抛出 `Illegal invocation`。

   根因是原生 `fetch` 以 `dependencies.fetcher(...)` 的对象方法形式调用，错误绑定了 receiver。修复将 fetcher 先捕获为局部函数，再直接调用；同时增加 receiver 回归测试。

5. 修复后，重启流程在打开 Popup 前明确断言 `storage.session.extensionBinding` 不存在；打开真实 Popup 后，受 E2E secret 保护的观测端点记录到 `/v1/extension/session/challenge` 和 `/v1/extension/session/renew` 各返回 201，并断言续签后的 access token 与重启前不同。这证明是持久设备 challenge/renew 和 token rotation，而不是误复用旧 session。

6. 真实 Popup 点击整页采集后，Popup → Service Worker → content script 消息链实际运行，但第一张 `captureVisibleTab` 因缺少真实用户手势授权安全失败。Manifest 已声明 `activeTab`；错误来自 Playwright 程序化 Popup 不授予该权限。测试据实断言 0 张切片、错误披露和没有“确认上传”按钮。

## 真实 Extension E2E 证据

- 加载本次生成的真实 unpacked Extension，固定扩展 ID 为 `mdbmlilohlhmjmcmkpbpjhldganompcl`。
- 通过 CDP 定位并操作真实 `chrome.action` Popup，不使用复制的网页替身。
- Popup 输入一次性配对码，服务端兑换返回 201；重放同一码返回通用 401。
- 配对后 workspace 成员数为 2，浏览器重启和续签后仍为 2，没有重复创建成员。
- Service Worker、content script、Chrome storage 和 IndexedDB 均为真实扩展运行边界。
- 重启前 session bearer 不持久化；原 device ID 与不可导出 P-256 私钥持久化。
- 新 Worker 经 challenge/renew 得到新的 Mock binding；续签前后 access token 不同。
- Popup 从 `chrome.commands.getAll()` 显示已分配快捷键；实际按键手势仍为 `not_run`。
- content overlay 显示 Mock Provider 和“遮挡敏感信息：关”。遮挡默认关闭。
- E2E 使用临时复制的 unpacked 目录，仅在该副本中增加 localhost host permission 以访问隔离测试 API；发布制品 Manifest 没有因此增加 `<all_urls>` 或测试 host permission。

最终命令与结果：

```text
pnpm --dir tests/e2e exec playwright test -c playwright.extension.config.ts
1 passed (16.0s)
```

## 整页组件证据

component-only 集成测试读取实际 `tests/e2e/fixtures/long-creator-page.html`，从 fixture marker、CSS computed height 和 viewport data attributes 得到 4000px 与 1280×800，再把同一数据依次传给真实 driver、位置相关 mock pixels、真实 stitcher 和真实 overlay：

- 滚动位置为 `0/800/1600/2400/3200/3200`；
- 产生 6 张切片；
- 拼接结果为 1280×4000；
- 完整性显示“完整”，overlay 显示“采集 6 屏”；
- 遮挡默认仍为关闭；
- 上传元数据合同覆盖 `capture_mode=full-page`、完整性、停止原因和切片数。

这些固定数字只属于合成夹具。真实页面人工验收必须按页面实际高度、viewport 和设备像素比自适应判断，不得固定要求 6 屏或 1280×4000。

## 全量门禁与合同验证

### API

在隔离随机 tmpfs PostgreSQL/Redis 以及对应 `TEST_DATABASE_URL`、`REDIS_URL` 下执行全量测试：

```text
1089 passed in 50.90s
Ruff: All checks passed!
MyPy: Success: no issues found in 174 source files
```

首次在未启动依赖时的 `1073 passed, 9 failed, 7 errors` 属于环境失败，不被记录为通过。隔离依赖就绪后还暴露了前序迁移断言仍停在 0035/0036 的问题；相关测试更新为当前 head `20260810_0037`，最终全绿。

便携验收合同聚焦复跑：

```text
uv run pytest -q tests/open_source/test_portable_acceptance_contract.py
12 passed
bash -n scripts/verify-portable-release.sh
passed
```

portable evidence 的 Extension 字段保持诚实的 `not_run`，并明确列出 `mock_upload`、`web_manual_confirmation`、`staging_object_cleanup`。其中 `cleanup=passed` 只表示 portable Compose 隔离资源清理通过，不代表真实 Extension 上传链已执行。

### Web

```text
54 test files passed
330 tests passed
lint passed
typecheck passed
```

### Extension

```text
pnpm --filter extension test
16 test files passed
176 tests passed
pnpm --filter extension lint
passed
pnpm --filter extension typecheck
passed
```

### 根级合同与安全检查

以下均通过：

- `pnpm schemas:check`
- `pnpm metrics:check`
- `bash scripts/secret-scan.sh`
- `git diff --check`
- `git diff --cached --check`
- Extension 离线制品验证：`release_artifact=clean`

brief 中写到的 `scripts/check-openapi-drift.sh`、`scripts/check-schema-consistency.sh` 和 `scripts/scan-secrets.sh` 在仓库中不存在。实际等价门禁为上述 `schemas:check`、`metrics:check` 和 `scripts/secret-scan.sh`；没有创建虚假的兼容 wrapper。

## 确定性 0.3.0 制品

固定 `SOURCE_DATE_EPOCH=1785744000`，连续两次执行：

```bash
SOURCE_DATE_EPOCH=1785744000 pnpm --filter extension package
```

两轮结果：

- unpacked 文件列表完全相同；
- unpacked 逐文件 SHA-256 完全相同；
- Chrome/Edge ZIP SHA-256 完全相同；
- unpacked 和每个 ZIP 均包含 11 个文件；
- 离线检查结果为 `release_artifact=clean`。

本地文件：

- 可加载目录：`apps/extension/release/unpacked`
- Chrome：`apps/extension/release/operations-capture-extension-chrome-0.3.0.zip`
- Edge：`apps/extension/release/operations-capture-extension-edge-0.3.0.zip`
- 两个 ZIP 的 SHA-256：`f5a11e2ee2e597c580b9591b908c38a248b77f96c245770c88fbb61284f20cf1`

打包采用根文件和 `assets/*.js` allowlist，拒绝符号链接、source map、日志、远程脚本、`eval`/`new Function`、常见 token/私钥、截图、测试目录、fixture、IndexedDB 数据和环境文件。生成制品是本地交接物，未创建 GitHub Release，也没有 push。

## 隔离与清理证据

- PostgreSQL 容器：精确名称 `operations_ai_extension_e2e_postgres_<runId>`，数据目录为 tmpfs。
- Redis 容器：精确名称 `operations_ai_extension_e2e_<runId>`，数据目录为 tmpfs。
- PostgreSQL schema：精确名称 `extension_pairing_e2e_<runId>`。
- 端口、bucket 名/对象前缀和浏览器 profile 每轮随机。
- teardown 在 schema 删除失败时仍继续删除本轮两个精确容器和 marker，聚合错误后再失败。
- teardown 对两个精确容器执行删除后 `docker inspect`，只有确认 `No such object/container` 才视为 absent。
- 临时 unpacked 副本和 profile 从复制、Manifest 修改、浏览器启动开始均置于 `try/finally` 清理边界内。
- 最终检查未发现 `operations_ai_extension_e2e*` 容器或 `operations_ai_extension_pairing_e2e_schema_*` marker。
- 早期中断诊断留下的 PID 64922/64929 经核对 cwd 和端口属于本 worktree 后精确 TERM；没有触碰未知进程。
- 未清理任何现有 Compose 项目、无关容器、网络、卷、浏览器扩展或用户数据。

## 独立只读 review

独立 reviewer 结论：无 Critical。最初报告 3 个 Important 和 1 个 minor，提交前全部修复：

1. **续签证据不足**：原测试只看到重启后有 binding，未证明 Popup 前 session 缺失、challenge/renew 实际发生或 token rotation。现已增加三项精确断言，并复跑 E2E 通过。
2. **清理不够失败安全**：schema drop 失败会提前抛出，容器删除没有验证；profile 复制或浏览器启动早期失败也可能泄漏。现已改为精确目标、聚合错误、finally 清理和删除后 inspect 验证。
3. **人工手册固定夹具指标**：原手册误要求任意真实页面都为 6 屏、1280×4000。现改为真实页面自适应验收，固定指标只作为组件夹具证据。
4. **portable `not_run` 列表不完整**：现已补入 Mock 上传、Web 人工确认和暂存对象删除，并增加合同断言；同时明确 `cleanup` 的 portable Compose 范围。

修复后复跑 Extension E2E、Extension 全量测试/lint/typecheck、portable contract、脚本语法、离线制品验证和资源 absent 检查，全部通过。

## macOS Chrome 人工 `not_run` 边界

以下项目没有自动化执行，必须由用户在 macOS Chrome 中按 `docs/acceptance/extension-0.3.0-macos-chrome.md` 完成：

- 加载或重载本地 unpacked 0.3.0；
- 从真实工具栏点击 Popup 或实际按下已分配快捷键；
- 由真实用户手势授予 `activeTab` 后执行 `captureVisibleTab`；
- 按真实页面高度核对“采集 N 屏”、完整性和预览尺寸；
- 上传前人工确认；
- 完成一次 Mock 上传和 Web 人工确认；
- 确认暂存对象随后删除；
- 关闭并重开 Chrome 后确认无需重新输入配对码即可续签；
- 分别验证可见区、选区、取消和失败降级。

另外保持 `not_run`：真实抖音/小红书页面、任何未明确授权的创作者页面、真实付费 Provider、Edge 运行时、Windows 运行时和 portable 包完整 Compose 启动验收。付费调用次数为 0、费用为 0。

## Commit、工作区与 concerns

- Task 7 产品、测试、文档和根级报告已提交为 `6456f5116a1cb58c8f329ad618b790d10d0943cf`，提交信息精确匹配 brief。
- 没有 push、merge、发布或操作用户浏览器。
- `.superpowers/brainstorm/` 和 `task-6-rereview-round-1.md` 为既有未跟踪内容，未读取、未修改、未提交。
- 本计划目录报告最初按后续协调要求补写，因此不包含在基线提交 `6456f51` 中；控制器修复轮将它与本轮证据一并纳入独立 fix commit。
- 最大剩余 concern 是 Chrome `activeTab` 的真实手势边界：在人工步骤完成前，不得声称完整浏览器截图、上传、Web 确认或暂存对象清理已通过。
- Chrome/Edge ZIP 与 unpacked 目录是当前工作区的本地生成物，不是已发布 Release；交接时应以本报告中的路径和 SHA-256 核对。
- 自动化只证明 Mock/local 隔离链。真实平台、真实数据、付费模型和跨平台兼容性均不在本次通过范围。

## 控制器修复轮 1/5：两个 Important

本轮遵循 RED → GREEN，未处理控制器列出的 Minor 根报告问题。

### Important 1：ZIP 跨时区不确定

RED 复现使用相同 `SOURCE_DATE_EPOCH=1785744000`：

- `TZ=UTC`：`7cfa3398e007ef03094f6bc79eb72d0a5182032874e459957c36303b4fac9c61`
- `TZ=Asia/Shanghai`：`c3e44b78f67eecf227fa3dada949a31b8e1cb93b930e7ae5acefde15df338f31`
- `cmp`：archives differ at byte 12。

根因是 `/usr/bin/zip` 把相同文件 mtime 转换为进程本地时区的 DOS 时间；同时压缩选择和 ZIP header 元数据仍由本机 Info-ZIP 决定，所以“同机连续两次相同”不足以证明可复现。

修复以仓库内确定性 ZIP writer 替换 `/usr/bin/zip`。writer 固定：

- entry 名称按 code-unit 排序；
- `SOURCE_DATE_EPOCH` 用 UTC getter 转换为 DOS date/time；
- UTF-8 flag、classic ZIP version 和 Unix create-system；
- regular file mode `0100644`；
- STORE compression；
- CRC-32、local header、central directory 和 EOCD 的字段与顺序。

GREEN：

- `TZ=UTC`：`f5a11e2ee2e597c580b9591b908c38a248b77f96c245770c88fbb61284f20cf1`
- `TZ=Asia/Shanghai`：`f5a11e2ee2e597c580b9591b908c38a248b77f96c245770c88fbb61284f20cf1`
- Chrome、Edge、跨 TZ 字节完全相同；
- 11 个排序 entry；
- unpacked 文件列表和逐文件 SHA-256 相同；
- Chrome/Edge `unzip -t` 均无错误；
- verifier 输出 `release_artifact=clean`。

自动测试 `tests/package-determinism.test.ts` 直接在 UTC/上海两种 TZ 调用打包器，比较 Chrome/Edge SHA 和字节，并解析 central directory 校验固定 UTC 时间、mode、creator、compression 和 entry 顺序。

### Important 2：fixture 未贯穿 component chain

RED：新增集成测试读取真实 long-page fixture 后得到 CSS computed height 4000px，但 fixture 没有可供 driver 使用的 viewport geometry，`data-e2e-viewport-width` 为缺失值，测试以 `expected NaN to be 1280` 失败。这证明原有三个测试只分别硬编码 driver、stitcher 和 overlay 输入。

修复在 synthetic fixture marker 上声明 `data-e2e-scroll-height=4000`、`data-e2e-viewport-width=1280`、`data-e2e-viewport-height=800`。新增的 component-only 集成测试随后：

1. 读取并由 JSDOM 渲染实际 fixture；
2. 断言 marker、CSS computed height 与声明 geometry；
3. 用 geometry 驱动真实 `ScrollCaptureDriver`；
4. 依据 driver 产生的每个 `scrollY` 生成逐行位置相关 mock pixels；
5. 把六个真实 driver slices 送入真实 `stitchSlices`，用实际像素行证明页底重复切片的 800px overlap；
6. 把 stitcher 输出送入真实 `CaptureOverlay`；
7. 断言六个位置、6 slices、1280×4000、complete、`采集 6 屏`、`遮挡敏感信息：关` 和完整 metadata；
8. 断言为用户手势段预留的 `captureVisibleTab` seam mock 调用次数为 0，继续把真实用户手势段标为 `not_run`。

GREEN 与本轮门禁：

- focused component/package tests：2 files，3 tests passed；
- Extension full：16 files，176 tests passed；
- Extension lint：passed；
- Extension typecheck：passed；
- Extension E2E：1 passed (16.0s)；
- release verifier：`release_artifact=clean`；
- Chrome/Edge unzip integrity：passed。

本轮未操作用户 Chrome、用户数据、真实平台或付费 Provider；未 push、merge 或 release。真实工具栏/快捷键手势、`captureVisibleTab`、其下游上传/Web 确认/暂存对象删除的 `not_run` 边界没有改变。
