# Capture Extension 配对与安全采集设计

## 目标

把现有 `0.1.0` 扩展从“只能绑定的工程骨架”升级为可在 macOS Chrome 本地测试的安全采集工具：用户不再创建或消耗成员邀请码，而是在已登录的运营工作台生成一次性连接码；扩展绑定当前成员后，可以在受支持的平台页面主动选择截图区域、遮挡敏感信息、上传识别，并回到 Web 完成人工确认。

本设计不宣称已经兼容真实抖音或小红书页面。真实页面仍需要用户授权后的人工验收；扩展只依赖受支持 URL 和用户手动选区，不伪造未经验证的 DOM 适配能力。

## 用户流程

### 连接扩展

1. Admin 或 Editor 登录私有工作区。
2. 在顶部“连接扩展”入口或“数据导入 → 浏览器扩展”入口点击“生成连接码”。
3. 服务端返回一次性 8 位连接码和 5 分钟倒计时；网页只展示一次。
4. 用户打开扩展。扩展默认使用本地 API `http://127.0.0.1:51201`，远程部署可在“高级设置”中填写 HTTPS API 根地址。
5. 用户输入连接码并点击“连接”。扩展获得绑定当前成员的受限令牌，不创建新的 `WorkspaceMember`，也不消耗成员邀请码。
6. 连接成功后显示工作区、成员、到期时间、处理模式和目标 Web 地址，不显示任何密钥或完整令牌。

### 安全采集

1. 用户自行登录抖音或小红书创作者平台，并进入支持的内容管理页面。
2. 打开扩展，页面卡片明确显示平台、URL 是否受支持和连接状态。
3. 点击“开始安全采集”后，内容脚本进入手动选区模式。用户拖拽选择当前可见区域；扩展不猜测不可见区域，也不滚动翻页。
4. 扩展临时隐藏自身浮层，通过 `activeTab` 捕获当前可见标签页，再按设备像素比裁剪。
5. 预览界面允许重新选区、取消、添加或删除矩形遮挡。上传前必须再次确认；截图不写入 `localStorage`、`chrome.storage.local` 或 URL。
6. 确认后上传至已有暂存任务 API，轮询 Mock 或已配置的 OCR/视觉识别结果。
7. 成功后显示“到运营工具确认”，打开服务端返回的 `web_origin + review_url`。用户选择平台账号、修正识别候选并人工确认后，数据才进入正式快照。

## 配对架构

### Web 会话端

新增 `POST /v1/workspaces/{workspace_id}/extension-pairing-codes`：

- 只接受有效 Web Session、CSRF 和 Admin/Editor 角色。
- Viewer、Demo 和扩展令牌不能创建连接码。
- 每个成员同时只保留一个未使用连接码；重新生成会使旧码失效。
- 返回 `pairing_code`、`expires_at`、`workspace_name`，连接码只返回一次。

工作台顶部和数据导入页共用一个 `ExtensionPairingPanel`，不复制配对逻辑。

### 服务端存储

新增 `extension_pairing_codes` 表：

- `workspace_id`、`member_id`、`code_digest`、`created_at`、`expires_at`、`used_at`、`revoked_at`。
- 连接码为排除易混字符的 8 位大写字符，使用服务端密钥 HMAC 后存储，不保存明文。
- 连接码 5 分钟过期，只能兑换一次；兑换成功与标记使用在同一数据库事务内完成。
- 按来源 IP 和连接码摘要限流，错误响应不区分“不存在、过期、已使用”，避免枚举。

新增 `POST /v1/extension/pair`：

- 输入连接码和固定 `client_id`。
- 成功后直接为连接码绑定的现有成员签发 `capture:create`、`capture:upload`、`capture:read` 令牌。
- 令牌有效期为 8 小时，仅存 `chrome.storage.session`；浏览器重启、主动解绑、成员撤销或令牌撤销后立即失效。
- 响应增加安全展示所需的 `workspace_name`、`member_display_name`、`web_origin`、`provider_mode` 和 `region`。
- 保留旧 `/v1/extension/bind` 接口用于兼容旧包，但新版 Popup 不再展示成员邀请码入口。

## 扩展结构

### Popup

Popup 分成三个明确状态：

- 未连接：连接码输入、默认本地服务器、高级服务器设置。
- 已连接但页面不支持：展示原因和支持的两个 URL 范围。
- 已连接且页面支持：展示“开始安全采集”、令牌剩余时间、处理模式、解绑。

所有错误使用面向运营人员的中文：连接码无效或过期、服务器不可达、页面不支持、截图失败、上传失败、识别超时。技术错误码只放在可展开详情中，不展示令牌、截图正文或供应商错误正文。

### Background Service Worker

Background 只承担：

- 查询并校验短期绑定。
- 接收内容脚本的用户主动截图请求。
- 使用 `chrome.tabs.captureVisibleTab` 捕获当前可见标签页。
- 把图片只返回给发起请求的当前标签页。

不新增 `cookies`、`webRequest`、`tabs` 或 `<all_urls>` 权限；继续使用 Manifest V3、`activeTab`、`scripting`、`storage` 和现有受限平台 host permissions。

### Content Script 与预览浮层

内容脚本只在两个已声明的创作者平台 URL 中运行。新版真实页面判断只依赖 hostname/path，不依赖测试 Fixture 的 `data-anchor`、`data-page-version` 或 `data-capture-region`。Fixture 元数据仍可用于自动化测试，但不会成为真实页面成功的必要条件。

预览浮层负责选区、裁剪、矩形遮挡和最终确认。状态机固定为：

`idle → selecting → capturing → previewing → uploading → processing → completed`

取消、URL 改变、标签页失焦、连接失效或截图尺寸变化会回到安全状态，不自动上传。图片只保存在页面内存和服务端暂存对象中；确认或取消继续使用现有幂等清理机制。

## 数据与权限边界

- 扩展只能创建、上传和读取自己的暂存采集任务，不能确认正式导入、读取内容库、管理成员或调用生成能力。
- Web 人工确认继续要求 Admin/Editor Web Session 和 CSRF；Viewer 只读。
- 工作区、成员、Token、任务和平台在服务端重新校验；跨工作区返回 404。
- 本地 Mock 模式必须明确显示“不会调用外部付费模型”；真实视觉配置必须显示地域和可能产生费用。
- 截图上传前显示目标服务器、平台、截图范围和遮挡数量。

## 安装与升级

交付版本升级为 `0.2.0`，Chrome 和 Edge 使用相同源码构建。完成自动化验收后：

1. 生成确定性 Chrome/Edge ZIP、哈希和 `unpacked` 目录。
2. 在用户当前 macOS Chrome 的 `chrome://extensions` 中开启开发者模式。
3. 加载新的 `unpacked` 目录；若已有旧开发版，先安全移除旧扩展或使用“重新加载”，不动其他扩展。
4. 完成一次本地连接码配对和脱敏测试页安全采集验收。

Windows、Edge 和真实平台页面保持 `not_run`，不因 macOS Chrome 本地验收而推断通过。

## 测试与验收

### API

- Admin/Editor 可以生成连接码，Viewer/Demo/扩展令牌被拒绝。
- 明文连接码不落库、不进日志、不进备份。
- 过期、重复兑换、并发兑换、旧码失效、限流和成员撤销均有测试。
- 配对只复用现有成员，不增加成员数；跨工作区资源返回 404。
- 新令牌只能访问三项采集 Scope。

### Extension

- Popup 三种状态、服务器高级设置、中文错误和令牌过期降级。
- 支持 URL 与不支持 URL 检测。
- 截图必须由用户点击触发；选择、裁剪、遮挡、重拍、取消和上传状态机。
- 上传幂等、401 重新配对、处理轮询、超时和 Web review 链接。
- Manifest 权限不扩大，构建产物无远程脚本、`eval`、密钥或 source map。

### Web 与 E2E

- 顶部和数据导入页均能生成连接码，Viewer 看不到写入口。
- 使用脱敏静态平台页面、真实打包扩展和隔离临时数据库，完成“生成连接码 → 配对 → 选择截图区域 → 遮挡 → 上传 → Mock 识别 → Web 人工确认”的全链路。
- 原 Web、API、Extension 测试、OpenAPI、生成 TypeScript、迁移、密钥扫描和生产构建全部通过。

## 不在本次范围

- 绕过平台登录、验证码、风控或反自动化限制。
- 自动翻页、自动滚动或后台无人值守批量采集。
- 自动发布内容。
- Agent 操控电脑采集。
- 真实平台 DOM 的未经验证自动识别。
- Windows、Edge、商店签名和 GitHub Release。

