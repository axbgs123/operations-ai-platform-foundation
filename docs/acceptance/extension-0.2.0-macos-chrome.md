# 浏览器采集助手 0.2.0 验收记录

## 自动化结果

状态：`passed_fixture_runtime`

隔离环境使用临时 PostgreSQL schema、临时 Redis、Mock Provider、两个独立浏览器上下文和合成创作者页面。实际 `release/unpacked` 扩展 Service Worker 被 Chromium 加载，完成：

1. Admin 生成一次性配对码。
2. 扩展兑换后仍复用当前成员，成员数保持 2。
3. 配对码重放返回通用 401。
4. 真实 Service Worker 在活动标签、URL、平台、页面版本和签名均匹配后，仅向真实 content script 提供采集所需的最小短期绑定；content script 挂载采集遮罩后取消。
5. 使用同一短期扩展令牌直接创建合成暂存任务，Mock 识别成功；自动化不声称执行了工具栏 Popup 的用户手势或 `captureVisibleTab`。
6. 扩展确认接口返回 403。
7. 独立 Editor Web 会话选择账号并确认正式快照。
8. 确认后暂存截图被清理。

发布 Manifest 使用固定公开身份 `mdbmlilohlhmjmcmkpbpjhldganompcl`。API CORS 仅允许 Web 来源和这个精确扩展来源；未知扩展来源不会获得跨域许可。content script 不能直接读取 `chrome.storage.session`。

验收记录不保存配对码、令牌、Cookie、CSRF、截图正文、标题、账号名称或 OCR 原文。没有访问真实平台页面、真实模型或计费服务。

## 确定性制品

固定 `SOURCE_DATE_EPOCH=1785744000` 连续构建两次，要求文件列表与 SHA-256 完全一致。Chrome 和 Edge 当前业务内容一致，差异仅允许未来显式声明的浏览器元数据。

最终提交后的确切 SHA-256 由 Task 6 报告记录。

## 尚未执行的人工步骤

macOS Chrome unpacked 包仍为 `not_run`，需由主验收会话完成：

1. 在 `chrome://extensions` 保留所有无关扩展。
2. 若旧版扩展来源路径相同则点击重载；路径不同则只移除旧“运营数据采集助手”。
3. 开启开发者模式并加载 `apps/extension/release/unpacked`。
4. 核对名称、版本 `0.2.0` 和权限；固定到工具栏是可选项。
5. 使用临时合成工作区，在 `http://127.0.0.1:51201` 完成配对；从工具栏 Popup 发起合成页面采集，实际执行选区、遮挡、`captureVisibleTab` 和上传。
6. 在 Web 完成人工确认，仅删除本次创建的合成记录和临时资源。

Windows、Edge、真实抖音/小红书页面和真实模型均保持 `not_run`。
