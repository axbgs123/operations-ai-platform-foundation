# ADR 0003: 千问 Provider 合同与安全边界

- 状态：Accepted for engineering implementation
- 官方合同核对日期：2026-07-29（Asia/Shanghai）
- 适用范围：千问 Provider 计划 Task 1—6

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

## Task 3：Qwen-OCR 高级识别合同

2026-07-28 再次核对官方文档后，截图与封面 OCR 固定使用精确快照
`qwen-vl-ocr-2025-11-20`，Catalog 状态保持 `experimental`，只声明
`Capability.VISION`。文本快照仍只声明 `Capability.TEXT`，两者不得互相扩大能力。

OCR 使用原生 DashScope Multimodal Generation HTTP 合同，而不是从 OpenAI
兼容协议的 Markdown 文本中猜测坐标。原因是官方明确说明旋转校正和内置 OCR
任务属于 DashScope 完整能力；请求固定
`ocr_options.task=advanced_recognition`、`enable_rotate=true`，只解析官方
`ocr_result.words_info`。

地域端点只能由服务端枚举地域及已校验的 Provider Workspace ID 构造：

```text
https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation
https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation
```

### 图片、像素与输出边界

- 业务只接收 PNG、JPEG、WebP；声明 MIME 必须与 Pillow 解码格式一致；
- 原始图片上限 7 MiB，确保服务端生成的 Base64 Data URL 仍低于官方 10 MiB
  编码字符串限制；
- 宽高必须各大于 10 像素，解码后总像素不得超过 8,388,608；
- 请求固定 `min_pixels=3072`、`max_pixels=8388608`；
- `max_tokens=4096`，不申请 4097—8192 的商务扩容；
- 解码后统一转 RGB 并重新编码，移除 EXIF、GPS、ICC、注释等元数据；
- 不发送本地路径、对象 Key、内部 URL，日志不记录图片、Base64 或 Data URL。

官方 location 是按原图左上角原点、顺时针四个顶点的 8 个绝对像素值；
`rotate_rect` 是中心点、宽、高、角度五元组。业务取四点的
`min(x), min(y), max(x), max(y)` 得到轴对齐框，再除以实际解码宽高得到
0—1 坐标。负数、越界、NaN、Infinity、零宽或零高直接拒绝，绝不修补。

官方高级识别合同没有经过校准的字段级 confidence。因此真实结果固定
`confidence_source=unavailable`、兼容置信度为 0、
`requires_human_review=true`；不得伪造 0.95/0.99。OCR 原文只作为不可信数据，
指标映射使用当前工作区及固定平台的受控标签表；未知标签只进入待复核文字，不进入
正式指标。

### 计费、数据发送与未验证项

计费按输入和输出 token；图片 token 计入输入，官方计算近似为缩放后像素数除以
1024，再加两个视觉标记 token。2026-07-28 官方价格页显示，北京快照输入/输出分别
为 0.3/0.5 元每百万 token，新加坡分别为 0.514/1.174 元每百万 token；价格可能
变化，真实验收前必须再次核对。

真实模式会把用户最终确认、已遮挡的截图内容发送到所选地域的阿里云百炼，并可能
产生费用；Provider Workspace ID 和密钥不返回扩展。扩展令牌仍不能确认正式数据，
识别候选只有在 Web 人工确认后才可写入快照。

本 Task 仅以 `httpx.MockTransport` 和人工合成图片验证合同。真实鉴权、真实图片
识别质量、真实 token 用量、地域连通性、限流、延迟、费用、抖音/小红书真实页面和
OCR 准确率均为 `not_run`，不得声称已生产验证。

官方依据：

- [Qwen-OCR 使用说明](https://help.aliyun.com/zh/model-studio/qwen-vl-ocr)
- [Qwen-OCR API 参考](https://help.aliyun.com/zh/model-studio/qwen-vl-ocr-api-reference)
- [模型价格](https://help.aliyun.com/zh/model-studio/model-pricing)

## Task 6：工作区用量治理与受控验证

所有真实千问 HTTP attempt 必须先经过工作区与 capability 维度的政策、UTC 每日
预算、每分钟调用上限和并发租约。没有有效政策、数据库或 Redis 状态不可靠、预算
不足时一律在 Provider 调用前 fail-closed；Mock 不消耗真实预算，并标记
`analytics_eligible=false`。

预算使用整数 CNY microunits，禁止 float。`pricing_version`
固定为 `aliyun-public-2026-07-29-v1`，每个 reservation/attempt 保存模型、地域和
价格版本，后续价格变化不得覆盖历史。当前冻结价格来自 2026-07-29 官方公开页面：

| 模型 | 地域 | 计价 |
|---|---|---|
| qwen3.5-plus-2026-04-20 | 北京 | 输入 0.8、输出 4.8 元/百万 token |
| qwen3.5-plus-2026-04-20 | 新加坡 | 输入 2.936、输出 17.614 元/百万 token |
| qwen-vl-ocr-2025-11-20 | 北京 | 输入 0.3、输出 0.5 元/百万 token |
| qwen-vl-ocr-2025-11-20 | 新加坡 | 输入 0.514、输出 1.174 元/百万 token |
| text-embedding-v4 | 北京 | 0.5 元/百万 token |
| text-embedding-v4 | 新加坡 | 0.734 元/百万 token |
| qwen-image-2.0-pro-2026-06-22 | 北京 | 0.5 元/张 |
| qwen-image-2.0-pro-2026-06-22 | 新加坡 | 0.550443 元/张 |

价格可能变化，真实验收前必须重新核对。并发使用 Redis 原子 Lua、有 TTL 的 lease
和随机 fencing token；续租与释放必须匹配 token，旧 Worker 不能释放新租约。
Provider 网络调用期间不持有数据库事务；每次 HTTP 重试单独预留、单独记录和结算。
明确未计费才释放，结果不确定保留预算并记录 `unknown`。

配置与密钥轮换形成新的 `configuration_version`。禁用后新任务不可调用；已发出的
请求仍按实际结果结算。失败不静默切换 Mock。验证记录绑定工作区、地域、能力、精确
模型、合同、配置及 suite 版本，并且不可变；单次通过不会升级全局 Catalog。

本 Task 未获真实调用和费用授权，所以受控验收固定记录为 `not_run`，原因
`explicit_user_authorization_missing`。所有能力继续为 `experimental`。后续只有
用户明确指定地域、能力和预算，并已通过 UI 安全保存密钥后，才能依照
[受控验收模板](../acceptance/qianwen-controlled-test-template.md) 单独执行。

Task 6 官方依据：

- [Qwen3.5-Plus](https://help.aliyun.com/zh/model-studio/qwen3-5-plus)
- [模型价格](https://help.aliyun.com/zh/model-studio/model-pricing)
- [模型限流](https://help.aliyun.com/zh/model-studio/rate-limit)
- [Embedding](https://help.aliyun.com/zh/model-studio/embedding)

## Task 5：封面视觉层合同

2026-07-29 依据百炼官方资料，封面视觉层固定使用精确快照
`qwen-image-2.0-pro-2026-06-22`，内部合同为
`qianwen-image-2.0-pro-2026-06-22-cover-layer-v1`，Catalog 状态保持
`experimental`。北京和新加坡均使用由服务端地域枚举与 Provider Workspace ID
构造的同步 Multimodal Generation 端点；客户端不能提供模型名、端点或原生 payload。

图片请求固定单轮 user message、`n=1`、`prompt_extend=false`、
`watermark=false`。只允许服务端 allowlist 中的 `seed` 和 `negative_prompt`；
零张参考图为文生图，一至三张为图片编辑。第四张 Provider 输入在计费前失败，不会
静默截断。输入只接受实际内容与声明一致的 PNG、JPEG、WebP，每张不超过 10 MiB，
边长不超过 3072，总像素不超过 3072×3072；动图、SVG、伪装或损坏内容拒绝。图片
重新编码并移除 EXIF/GPS/ICC，Base64 只存在于 Adapter 调用内存。

输出固定一张，产品允许的总像素为 512×512 至 2048×2048。官方临时结果 URL
有效期为 24 小时，但只作为即时下载入口：每次 HTTPS 跳转都执行 DNS、实际连接
地址、私网/元数据地址、响应大小、MIME、静态图片、像素和目标尺寸校验，随后重新
编码为 PNG。临时 URL、完整响应和图片正文不进入日志、数据库、API 或备份。

千问只生成背景和主体视觉。标题、副标题、品牌名、Logo、安全区和最终中文排版由
`cover-layout-v1` 在本地完成；Logo 永不作为 Provider 参考图。最终 PNG 仍进入
OCR/RiskRAG。当前没有可声明为可靠的真实封面 OCR 结果时，门禁持久化
`unavailable` OCR 扫描并强制人工复核，绝不把缺少 OCR 伪装为安全。

图片生成是可能计费的非幂等操作。单个 attempt 最多一次 Provider POST，Celery 和
HTTP 均不自动重试；请求是否到达 Provider 无法判断时记录
`MODEL_PROVIDER_OUTCOME_UNKNOWN`。admin/editor 只有显式创建新 attempt 才能重试，
并保留 previous attempt 关系和可能重复计费提示。相同 API 幂等范围及相同请求指纹
返回原任务，不同指纹冲突。

Provider 层先写工作区隔离 staging；程序化合成和风控完成后才登记正式引用。对象
存储与数据库发布失败时登记 `managed_objects` 并进入
`compensation_required`；取消任务把未发布对象转为立即可清理的 scheduled 状态。
成功来源只保存模型、地域、配置/合同版本、输入资产版本和哈希、安全 request ID、
输出对象与哈希、布局/OCR/RiskRAG 版本，不保存密钥、Provider Workspace ID、
Prompt 副本、签名 URL、临时 URL、Base64、二进制或供应商错误正文。

2026-07-29 官方价格页显示，北京为 0.5 元/张，新加坡为 0.550443 元/张，公开
限流为 2 RPM；价格与限流可能变化，Task 6 真实验收前必须重新核对并设置预算。
本 Task 只使用 MockTransport、固定 Mock 和人工合成图片，真实鉴权、地域连通性、
效果、延迟、审核行为、费用及保留行为均为 `not_run`。

官方依据：

- [Qwen-Image 2.0 Pro](https://help.aliyun.com/zh/model-studio/qwen-image-2-0-pro)
- [Qwen-Image API](https://help.aliyun.com/zh/model-studio/qwen-image-api)
- [图片编辑指南](https://help.aliyun.com/zh/model-studio/qwen-image-edit-guide)
- [文生图说明](https://help.aliyun.com/zh/model-studio/text-to-image)
- [模型价格](https://help.aliyun.com/zh/model-studio/model-pricing)

## Task 4：文本 Embedding 合同

2026-07-28 核对百炼官方向量化文档后，RiskRAG 固定使用官方模型标识
`text-embedding-v4`，内部合同固定为
`qianwen-text-embedding-v4-d1024-v1`，维度固定为 1024。官方资料没有提供可确认的
日期快照，因此这不是供应商快照级复现合同；Catalog 继续标记 `experimental`，
不得使用 `latest`，也不得声称上游模型行为不可变。模型标识、内部合同或维度任一
变化都必须重建索引。

两地使用服务端构造的 OpenAI-compatible Embeddings 端点：

```text
https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/embeddings
https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1/embeddings
```

每批最多 10 条。北京 `text-embedding-v4` 单批总上限为 33,000 Token，新加坡为
8,192 Token；可选维度包括 2048、1536、1024、768、512、256、128、64。本产品
固定 1024。应用只以保守的字符数和 UTF-8 字节数做预检，并明确不把字符数当作
Token 数；供应商仍负责执行地域 Token 上限。

响应必须包含与输入数量完全一致的 `data` 数组。每个 `index` 必须存在、唯一且落在
输入范围内；向量必须恰好 1024 维，所有元素必须是有限数字且不能为 bool，零向量、
NaN、Infinity、缺失、重复和越界均失败。不补零、不截断、不强转、不猜测顺序。

401、403 和普通 4xx 不重试；429、超时和 5xx 最多重试一次，一个业务批次最多两次
HTTP 请求。每次尝试都可能计费。安全日志只记录 Provider、模型、内部合同、维度、
输入条数、安全 request ID、供应商明确返回的 Token 用量、延迟、尝试次数和稳定
错误码，不记录正文、向量、密钥或供应商错误正文。

千问重建只处理当前工作区已授权、active、已生效且平台匹配的私有知识。不得使用
某个私人工作区的密钥处理全局公共知识；公共知识继续使用独立受控的 Mock/预建索引，
或返回 `MODEL_CONFIGURATION_REQUIRED`。本 Task 只使用 MockTransport 和人工合成
资料，未调用真实 API、未产生费用。

官方依据：

- [向量化与 OpenAI 兼容 Embeddings](https://help.aliyun.com/zh/model-studio/embedding)
- [模型限流](https://help.aliyun.com/zh/model-studio/rate-limit)
- [错误码](https://help.aliyun.com/zh/model-studio/error-code/)
- [模型价格](https://help.aliyun.com/zh/model-studio/model-pricing)
