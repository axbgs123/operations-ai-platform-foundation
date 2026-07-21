# 运营数据采集扩展 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 扩展只在本地测试页和获得授权的真实页面做验证，不自动化绕过登录或验证码。

**Goal:** 交付 macOS/Windows 可用的 Chrome/Edge Manifest V3 扩展，在抖音和小红书受支持的单条作品详情页完成安全截图、上传识别、人工确认和可选一键采集。

**Architecture:** 扩展 service worker 管理短期令牌和流程状态；content script 只负责支持页识别、高亮与遮挡 UI；`captureVisibleTab` 捕获用户当前可见标签页；API 负责截图暂存、识别和确认入库。扩展不读取 Cookie、密码、历史或隐藏接口。

**Tech Stack:** TypeScript、Manifest V3、Chrome Tabs/Scripting/Storage API、Vite、Vitest、Playwright Extension tests；现有 FastAPI Imports API。

**Global Constraints:** 默认安全模式；一键模式必须在同一已验证页面成功安全采集后由用户主动开启；一键仅省略区域/上传确认，识别数据仍必须确认。页面失配、敏感区域扩大、验证码或失败时自动退回安全模式。

## Task 1: 扩展脚手架、最小权限与构建

**Files:**
- Create: `apps/extension/package.json`, `vite.config.ts`, `manifest.json`
- Create: `apps/extension/src/background.ts`, `popup/**`, `content/**`
- Test: `apps/extension/tests/manifest.test.ts`

1. 测试 manifest 版本为 3，只声明 `activeTab`、`scripting`、必要 storage 权限和明确的抖音/小红书运营后台 host_permissions；禁止 `tabs` 全量历史读取、cookies、webRequest 阻断权限和 `<all_urls>`。
2. 构建 Chrome 与 Edge 共用产物；版本和受支持页面清单写入构建元数据。
3. 运行 `pnpm --filter extension test && pnpm --filter extension build`，预期无远程代码和 CSP 违规。
4. Commit: `feat: scaffold least-privilege capture extension`

## Task 2: 服务器绑定与短期令牌

**Files:**
- Create: `apps/api/app/modules/imports/extension_auth.py`, `extension_router.py`
- Create: `apps/extension/src/auth/**`
- Test: `apps/api/tests/imports/test_extension_auth.py`, `apps/extension/tests/auth.test.ts`

1. 测试用户输入服务器地址和邀请码后，API 返回受限、短期、可撤销令牌；原邀请码调用完成后从内存清除且不落长期 storage。
2. 令牌 scope 只允许创建截图暂存任务和读取自身任务；不能直接确认指标、访问内容库或管理工作区。
3. 服务器地址必须 HTTPS（localhost 开发例外），UI 始终显示目标服务器与视觉模型/处理说明。
4. Commit: `feat: bind extension with scoped short-lived tokens`

## Task 3: 支持页检测和默认安全模式

**Files:**
- Create: `apps/extension/src/content/page-adapters/base.ts`, `douyin.ts`, `xiaohongshu.ts`
- Create: `apps/extension/src/content/overlay.ts`, `redaction.ts`
- Fixture: `apps/extension/tests/fixtures/pages/**`
- Test: `apps/extension/tests/page-detection.test.ts`, `safe-mode.test.ts`

1. 使用脱敏静态 HTML 固件测试受支持 URL、详情页关键锚点、页面版本、采集区域和敏感区域；不匹配时必须停止。
2. 用户点击采集后先高亮区域，再用 `captureVisibleTab`；提供裁剪、矩形遮挡、重拍和取消；上传前显示最终预览。
3. 只捕获当前可见内容，不滚动拼接完整页面、不读取隐藏 DOM 数据。
4. Commit: `feat: implement preview-first safe capture mode`

## Task 4: 上传、识别轮询和 Web 人工确认

**Files:**
- Create: `apps/extension/src/capture/upload.ts`, `task-status.ts`
- Modify: `apps/api/app/modules/imports/extension_router.py`
- Test: `apps/extension/tests/upload.test.ts`, `apps/api/tests/imports/test_extension_capture.py`
- E2E: `tests/e2e/extension-safe-capture.spec.ts`

1. 上传内容只含截图、平台、支持页版本、本地时间和必要页面标识；请求日志不含截图正文或令牌。
2. API 写 staging 并返回 task；扩展显示队列/运行/成功/失败；成功后打开 Web review URL，用户修改确认后才入库。
3. 重复上传使用幂等键；网络断开可重试但不重复建立快照。
4. E2E 在两平台测试页完成截图→Mock 识别→人工确认→快照入库。
5. Commit: `feat: connect extension capture to reviewable imports`

## Task 5: 可选一键模式与自动降级

**Files:**
- Create: `apps/extension/src/capture/trust-state.ts`, `one-click.ts`
- Test: `apps/extension/tests/one-click.test.ts`, `fallback.test.ts`

1. 信任状态按 `server + platform + page_signature + extension_version` 保存；只有安全模式成功且用户明确开启才能一键。
2. 一键省略区域和上传预览，但 popup 显示“识别结果仍需在 Web 确认”和一键关闭选项。
3. 页面 signature 变化、敏感区域新增、验证码、捕获异常或识别失败立即清除信任并退回安全模式；不尝试绕过。
4. Commit: `feat: add opt-in one-click capture with fail-safe fallback`

## Task 6: 真实页面验证清单、隐私和发布包

**Files:**
- Create: `docs/open-source/extension-installation.md`, `docs/open-source/extension-privacy.md`
- Create: `apps/extension/supported-pages.json`, `apps/extension/PRIVACY.md`
- Test: `apps/extension/tests/supported-pages.test.ts`

1. 每个平台记录 URL 模式、最近验证日期、浏览器/系统、可识别字段、已知缺失字段和页面 signature；真实验证只在用户自行登录并主动测试时进行。
2. 分别在 Chrome/Edge、macOS/Windows 完成人工验收；无法取得某环境时明确标记“未验证”，不能声称支持已完成。
3. 检查打包内容不含服务器地址、邀请码、令牌、页面截图和测试账号数据。
4. 运行主计划 Gate A、扩展测试和 E2E。Commit: `docs: package verified capture extension safely`
