# 模型适配边界

文本生成、数据分析、视觉/OCR、封面和 Embedding 分别由 Adapter 接口实现。API 选择能力、验证结构化输出和保存版本；Web/扩展不直接调用 Provider。当前默认是确定性 Mock：Mock LLM、Mock OCR/视觉、Mock 封面和固定 Mock Embedding 可验证队列、解析、权限与回归流程，但不能说明真实模型质量、成本、延迟或审核通过率。

未来 Provider 必须通过配置启用：密钥仅在服务端加密保存，按工作区隔离与最小权限访问；显式配置数据发送提示、超时、有限重试、限流、成本和错误降级。失败保留已确认数据，绝不静默跨供应商切换；Embedding 配置变化后必须重建索引。Provider 适配器需要标明已验证/实验性/社区/不兼容等级。

## 千问结构化文本合同

千问 Task 1 已实现工程合同，但尚未进行真实计费 API 验收。服务端 Catalog 只开放
`qwen3.5-plus-2026-04-20` 的 `text` 能力，协议为 OpenAI-compatible Chat
Completions，状态固定为 `experimental`。配置仅允许 `cn-beijing` 和
`ap-southeast-1`；端点由受控地域与严格 Provider Workspace ID 构造，API 不接受
任意 `base_url`。

结构化请求关闭 thinking、禁用流式输出并要求 JSON object。响应只经过一次 JSON
解析和 Pydantic 严格验证，不移除 Markdown、不提取说明文字、不修补错误字段。401、
403 和普通 4xx 不重试；429、超时与 5xx 最多重试一次。失败不会静默切换到 Mock
或其他 Provider。完整合同见 [ADR 0003](0003-qianwen-provider-contract.md)。

本仓库不含任何真实 API Key。普通 CI 只使用 Mock/Fake Transport，不访问百炼、不
产生模型费用。无模型配置时，内容、导入、数据计算与恢复仍可使用，AI 操作返回可
理解的配置提示。真实效果、延迟、费用、限流与地域可用性均留待 Task 6 受控验收，
在此之前不得声明千问 Adapter 已 `verified` 或生产可用。
