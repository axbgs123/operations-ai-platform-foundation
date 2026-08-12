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

## 千问配置与用量治理

工作区设置页 `/workspaces/{workspaceId}/settings/models` 只从服务端 Catalog 展示
固定 Provider、模型和地域；没有 `base_url` 或任意模型输入。admin 可保存/轮换加密
密钥、设置 capability 预算并创建单能力受控验证；editor/viewer 只能读取不含密钥、
密文和 Provider Workspace ID 的安全状态。空白密钥保留原值，新密钥或端点/状态
变化创建新的配置版本。

真实调用执行“短事务 reservation → Redis 原子 rate/lease → 无数据库事务的
Provider HTTP → 新短事务追加 attempt 并结算”。预算按 UTC 00:00 划分，金额使用
整数 CNY microunits。每次 Provider HTTP attempt 独立记录；估算、已结算和结果未知
不能混为一类。没有政策、Redis 故障或预算不足时 fail-closed，admin 也不能绕过。
Mock 不进入真实费用汇总。

当前受控真实验收为 `not_run`，原因
`explicit_user_authorization_missing`；这不阻断 Mock/Fake 工程回归，但 Catalog
继续保持 `experimental`。

## 自带 OpenAI 兼容文本模型

工作区管理员也可以配置 `provider=openai_compatible`，用于团队自建或自行购买的
OpenAI Chat Completions 兼容文本服务。当前合同只覆盖 `GET /models` 和结构化
`POST /chat/completions`，不承诺兼容视觉、OCR、Embedding、图片生成、流式响应或
供应商专有功能。模型密钥只在服务端加密保存，读取接口不返回密钥、密文或完整端点。

服务地址在保存和每次请求前都经过 SSRF 防护：正式环境只允许公开 HTTPS 地址，拒绝
私网、回环、云元数据、URL 凭据、危险路径和重定向；开发环境仅显式允许 localhost。
“测试连接”只请求 `/models` 并核对模型 ID，不发送 Prompt 或运营数据。结构化生成
仍执行严格 JSON Schema 校验、工作区用量治理和安全错误映射，失败不会静默切换到
Mock 或千问。第三方价格未知，因此费用记为未知并由使用者直接向供应商结算，不能
把未知费用展示为 0 元。配置说明见
[接入自有 OpenAI 兼容文本模型](../open-source/openai-compatible-model-configuration.md)。

## 运营智能体对话投影

运营智能体在原“任务与执行”工作台之外新增“对话”入口。聊天会话和消息按工作区与
成员双重隔离并持久化；刷新或服务重启后可以继续读取。模型只返回严格的问候、澄清、
解释状态或创建计划意图，不能自行选择账号、调用任意工具、批准计划、发布内容或声称
操作已经完成。用户明确提出目标时，服务端仍调用原有 `PlanService` 创建可检查计划，
之后的批准、运行、确认、风控与结果继续由原 `AgentExecutor` 状态机负责。

用户消息先独立提交并释放数据库事务，再调用外部模型；模型失败时保留消息并追加安全
错误，日志不记录聊天正文。聊天历史最多向模型发送最近 12 条、合计 12,000 字。当前
JSON/ZIP 备份不导出聊天正文，跨机器迁移聊天历史尚未实现；本机数据库正常重启不受
此限制。完整使用边界见
[运营智能体对话与原任务执行](../open-source/operations-agent-chat.md)。

## 千问 Embedding 与索引代际

RiskRAG 千问向量固定 `text-embedding-v4`、内部合同
`qianwen-text-embedding-v4-d1024-v1` 和 1024 维，状态为 `experimental`。官方没有
已确认的日期快照，上游行为可能变化；模型、合同或维度变化必须建立新 generation。

重建采用蓝绿发布：短事务冻结工作区、平台、配置版本和 chunk 指纹，关闭 Session
后按最多 10 条调用 Provider，再用新事务写入 inactive generation。完整性、维度、
工作区、平台、配置和 claim/lease/fencing 全部复核后，才在一个事务内停用旧
generation 并激活新 generation。构建失败、发布回滚或旧 Worker 失去 claim 时，
旧 active generation 继续可检索；旧 generation 只由后续受控保留任务回收。

检索由服务端解析工作区与平台的 active generation，并同时绑定 provider、
model_config_id、config version、合同、维度和 generation。调用者不能选择旧模型
或旧 generation。元数据过滤仍在向量排序前执行；没有匹配活动索引时返回
`RISK_INDEX_REBUILDING`、`MODEL_CONFIGURATION_REQUIRED` 或
`NO_ACTIVE_RISK_EVIDENCE`，不得混用旧向量或生成虚假引用。

## 千问封面视觉层

封面图片 Adapter 固定为 `qwen-image-2.0-pro-2026-06-22` 和
`qianwen-image-2.0-pro-2026-06-22-cover-layer-v1`。它只生成背景/主体视觉；
中文标题、副标题、品牌名、Logo 与安全区始终由程序化布局绘制。template 不调用
Provider；ai_visual、hybrid、custom 分别按零至三张已授权参考图选择文生图或图片
编辑。Logo 只在本地合成。

参考图在工作区、内容归属、对象状态、版本、大小、MIME 和像素复核后重编码，Provider
输入 Base64 只存在于调用内存。Provider 临时输出 URL 经 SSRF、重定向、连接地址、
大小、MIME、解码和尺寸校验后立即转为受控 PNG，不保存临时 URL。

图片调用没有自动重试。超时或连接结果不确定时进入
`provider_outcome_unknown`，人工重试创建新 attempt 并串联历史。Worker 网络调用
期间不持有数据库事务；claim、lease 和 operation version 阻止取消后的旧 Worker
发布。成功产物保留不可变来源，失败/取消对象复用 `managed_objects`、保留策略与
工作区删除流程。当前仅完成工程合同与 Mock 验证，真实调用留待 Task 6。
