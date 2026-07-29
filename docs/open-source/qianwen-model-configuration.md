# 千问配置、用量与受控验收

千问适配器覆盖文本生成、运营分析、OCR、RiskRAG 文档/查询 Embedding，以及封面
文生图和图片编辑。当前所有能力均为 `experimental`：Mock/Fake Transport 回归通过
不代表供应商真实兼容、内容质量、长期稳定性或平台过审率。真实 API 验收尚未运行，
状态为 `not_run`，原因是 `explicit_user_authorization_missing`。

## 安全配置与权限

管理员在工作区设置页 `/workspaces/{workspaceId}/settings/models` 从服务端 Catalog
选择固定模型与地域。页面不接受任意 Provider、模型、capability 或 `base_url`。
Provider Workspace ID 和 API Key 只在写入请求中提交，读取响应不返回它们、密文或
任何密钥片段；API Key 成功保存后从组件内存清除，也不写浏览器持久化存储。不要把
密钥放入聊天、Issue、日志、命令行、测试 Fixture 或 `.env`。

admin 可创建、更新、轮换或禁用配置，设置预算并发起单能力受控验证；editor 和
viewer 只能读取安全状态，demo 只展示 Mock。所有操作重新校验工作区，跨工作区资源
返回 404。北京和新加坡的密钥及 Provider Workspace ID 不可混用。

密钥轮换、地域、Provider Workspace ID 或状态变化会形成新的
`configuration_version`。旧任务必须继续使用冻结版本或安全失败，不会静默切换新
配置。禁用配置后，新任务在调用 Provider 前失败；已经发出的请求仍按真实结果结算。
千问失败不会静默降级为 Mock。需要回滚时，管理员应显式禁用千问配置并选择 Mock。

## 数据发送与费用

只有显式选择千问且通过配置、权限和预算门禁的操作会向所选地域发送完成该能力所需
的最小数据：文本/分析发送相应结构化文本，OCR 发送经校验的图像，Embedding 发送
待向量化文本，封面生成发送合成提示和可选的经净化参考图。Prompt、用户正文、图片、
Base64、向量、密钥、Provider Workspace ID、Authorization/Cookie、完整供应商响应
和供应商错误正文均不得进入用量日志。

用量政策按 `workspace + capability` 生效。每日边界固定为 UTC 00:00，金额使用整数
CNY microunits，并冻结 `pricing_version`。`estimated` 表示供应商未返回精确 usage
时采用已记录估算；`settled` 表示根据明确 usage 或明确未计费结果结算；`unknown`
表示请求结果或计费无法确认，保守 reservation 不释放，等待人工处理。取消任务不
等于供应商未计费。

默认没有真实调用政策，因此真实调用 fail-closed。Redis 速率/并发状态或数据库状态
不可靠时同样拒绝调用；admin 也不能绕过。Mock 标记
`analytics_eligible=false`，不消耗真实预算。当前服务端硬上限为：并发 8、每分钟
600 次、每日 10,000 次、输入 100,000,000 token、输出 20,000,000 token、
Embedding 100,000,000 token、OCR 10,000 张、生成 1,000 张、费用
100,000,000 CNY microunits。政策字段的 `0` 表示禁止，不表示无限。

## 受控真实 API 验收

真实验收只能由 admin 对单一地域、capability、精确模型和配置版本主动发起，必须
设置最大调用次数、token/图片数、费用上限并确认真实调用。服务端只在调用边界解密
已保存凭据，使用人工合成输入，记录安全 request ID、延迟、usage、费用和稳定错误
码，不保存输入输出正文。北京与新加坡、不同能力和不同模型必须分别验证；页面不提供
默认“一键验证全部模型”。

后续执行真实验收前，用户还必须另行明确授权地域、能力和最大预算，并已通过 UI
安全保存密钥。当前没有该授权，所以工具只生成不可变 `not_run` 记录，不访问外网、
不使用真实 Key、不产生费用。详见
[受控验收模板](../acceptance/qianwen-controlled-test-template.md)。

## 隐私、备份与运维

模型配置、API Key 及密文、Provider Workspace ID、内部 reservation、验证输入输出、
临时对象和签名 URL 均不进入工作区备份。恢复后的工作区不会继承来源工作区的真实
Provider 权限或费用政策，必须重新配置。用量记录只保留必要关联 ID、模型/地域/版本、
计数、费用、延迟、安全 request ID 和稳定错误码。

Embedding 配置变化后需要建立新 RiskRAG generation。旧 generation 仍按现有受控
保留策略处理；Task 4 已知的旧 Embedding generation 清理事项尚未自动完成，运维方
不得手工删除可能仍被历史扫描引用的 generation。
