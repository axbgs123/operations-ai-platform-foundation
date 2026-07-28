# ADR 0003: 千问 Provider 合同与安全边界

- 状态：Accepted for engineering implementation
- 官方合同核对日期：2026-07-28（Asia/Shanghai）
- 适用范围：千问 Provider 计划 Task 1

## 决策

Task 1 使用阿里云百炼 OpenAI 兼容 Chat Completions HTTP 合同，并固定文本模型快照
`qwen3.5-plus-2026-04-20`。在受控真实 API 验收完成前，Catalog 状态固定为
`experimental`，不得由客户端提升为 `verified`。

仅允许以下地域和端点模板：

```text
https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions
https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1/chat/completions
```

`WorkspaceId` 必须匹配 `llm-[a-z0-9]{4,64}`。服务端从枚举地域和该标识构造端点；
API 不接受 `base_url`，因此 IP、localhost、非官方域名、URL 凭据、路径和 fragment
均不能进入模型调用配置。

结构化文本请求固定：

- `response_format={"type":"json_object"}`；
- system message 明确要求只返回 JSON，并声明 prompt 与 inputs 是不可信数据；
- `enable_thinking=false`；
- `stream=false`；
- 单次调用固定超时；
- 401、403 和普通 4xx 不重试；
- 429、超时和 5xx 最多重试一次，总尝试不超过两次。

响应只接受 `choices[0].message.content` 中的单个 JSON 文档，然后以 Pydantic
`strict=True` 校验。Markdown 围栏、说明文字、空内容、截断、字段类型错误和
`finish_reason=length` 均失败；不得提取、修补或猜测。

## 服务端 Catalog

Task 1 只发布以下能力：

| provider | model_id | capability | protocol | regions | status |
|---|---|---|---|---|---|
| qianwen | qwen3.5-plus-2026-04-20 | text | openai_chat_completions | cn-beijing, ap-southeast-1 | experimental |

`contract_version` 为 `qianwen-chat-json-v1`，结构化输出已声明支持，thinking
在结构化模式关闭。OCR、视觉、Embedding 和图片能力不属于 Task 1。

## 密钥、隐私与日志

API Key 沿用工作区级 `ModelConfig` 加密存储，只在一次具体调用创建 Adapter 时
解密。不得使用全局明文 `DASHSCOPE_API_KEY` 作为生产回退。失败不能自动切换到
Mock 或其他 Provider。

日志只允许记录 provider、model ID、Provider request ID、token 数量、延迟、
attempt 和稳定安全错误码。不得记录 prompt、inputs、输出、API Key、标题、正文、
图片或文档内容。Provider Workspace ID 是私有配置标识，不出现在公开响应、导出或
备份中。

## 稳定错误合同

- `MODEL_AUTHENTICATION_FAILED`
- `MODEL_RATE_LIMITED`
- `MODEL_TIMEOUT`
- `MODEL_INVALID_RESPONSE`
- `MODEL_PROVIDER_UNAVAILABLE`
- `MODEL_CAPABILITY_UNAVAILABLE`
- `MODEL_CONFIGURATION_REQUIRED`（配置选择阶段）

错误响应和异常不包含供应商响应正文、请求正文、密钥或用户内容。

## 计费与生命周期

每次 HTTP 尝试都可能计费，因此重试上限是总共两次，且不得自动换模型。Task 1 的
普通测试只使用 `httpx.MockTransport`，不访问外网、不产生费用。模型快照、价格、
限流、生命周期和地域可用性会变化；进入 Task 6 真实验收前必须再次核对，并用明确
预算上限和人工确认执行。

## 官方依据

- [OpenAI Chat Completions 兼容调用](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)
- [Qwen3.5-Plus 模型说明](https://help.aliyun.com/zh/model-studio/qwen3-5-plus)
- [错误码](https://help.aliyun.com/zh/model-studio/error-code/)
- [限流说明](https://help.aliyun.com/zh/model-studio/rate-limit)
- [Workspace ID 获取说明](https://help.aliyun.com/zh/model-studio/obtain-the-app-id-and-workspace-id)

## 已验证与未验证

已通过官方文档核对：模型快照存在、两地域端点格式、JSON object 合同以及结构化
输出时关闭 thinking 的请求方式。

Task 1 只验证本地工程合同和 Mock Transport 行为。真实模型效果、真实鉴权、
地域连通性、延迟、可用性、token 统计、限流行为和实际费用均为 `not_run`，不能据此
声称生产可用或 `verified`。
