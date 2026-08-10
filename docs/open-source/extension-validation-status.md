# 浏览器采集助手验证状态

合成 Fixture、隔离浏览器或打包通过，都不能替代真实平台页面验收。

## 已有证据

- 抖音和小红书适配器通过脱敏合成 HTML Fixture 测试。
- `0.2.0` 的实际 unpacked 构建已在隔离 Playwright Chromium 中加载 Service Worker，并完成配对、选区、遮挡、上传、Mock 识别和 Web 人工确认闭环。
- 配对码复用被拒绝，绑定前后成员数不变；扩展确认接口返回 403。
- 确认完成后，暂存截图生命周期清理已有自动化验证。
- Chrome 和 Edge 发布包来自同一业务源码；固定 `SOURCE_DATE_EPOCH` 重复构建的文件表和 SHA-256 相同。
- 自动化验收没有打开真实抖音或小红书页面，也没有调用真实或计费模型。

## 环境矩阵

| 环境 | 合成扩展运行 | 真实平台页面 |
| --- | --- | --- |
| 隔离 Playwright Chromium / macOS | 已验证 | 未运行 |
| 用户 macOS / Chrome unpacked 包 | 未运行，等待人工安装验收 | 未运行 |
| macOS / Edge | 未运行 | 未运行 |
| Windows / Chrome | 未运行 | 未运行 |
| Windows / Edge | 未运行 | 未运行 |

这些环境互相独立。某一浏览器或系统的证据不能用于标记另一个环境。

## 升级规则

只有获得授权的用户完成[真实页面人工验证模板](extension-real-page-validation-template.md)后，才能把对应环境标记为 `real_page_verified`。证据不得包含账号名、Cookie、截图、私有业务数据、密码、成员邀请码、配对码、Bearer 令牌或验证码内容。

如果页面锚点、采集区域、敏感区域、页面版本或签名变化，状态必须改为 `stale`，扩展退回安全模式，直到重新验证。
