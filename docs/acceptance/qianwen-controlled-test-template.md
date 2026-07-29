# 千问受控真实 API 验收模板

> 当前记录：`not_run`
> 原因：`explicit_user_authorization_missing`
> 外网访问：否；真实密钥使用：否；费用：CNY 0。

本模板只用于发布前、由工作区管理员主动批准的精确合同验证。普通 CI、开发测试和
本文档生成过程只使用 Mock/Fake Transport。不得把 API Key 放入聊天、命令行参数、
测试 Fixture、源码或 `.env`；密钥必须先通过 Web 设置页加密保存，由服务端仅在
单次 Provider 调用边界解密。

## 授权前置条件

- [ ] 用户再次明确授权真实 API 调用。
- [ ] 指定唯一地域：`cn-beijing` 或 `ap-southeast-1`。
- [ ] 指定唯一 capability 和精确 model_id；不得默认“一键验证全部”。
- [ ] 明确最大调用次数、token/图片数量和 CNY microunits 预算。
- [ ] 工作区已通过 UI 保存对应密钥和 Provider Workspace ID。
- [ ] 工作区 capability 用量政策已启用，且预算 reservation 成功。
- [ ] 测试输入为纯人工合成内容，不含运营数据、用户图片或私有知识。

## 单次验收记录

| 字段 | 值 |
|---|---|
| workspace_id | |
| region | |
| capability | |
| exact model_id | |
| contract_version | |
| configuration_version | |
| validation_suite_version | `qianwen-controlled-contract-v1` |
| max_calls | |
| max_input_tokens | |
| max_output_tokens | |
| max_images | |
| max_cost_microunits | |
| pricing_version | `aliyun-public-2026-07-29-v1` |
| started_at / completed_at | |
| result | `passed` / `failed` / `not_run` |
| stable error code | |
| safe Provider request ID | |
| latency_ms | |
| usage_basis | `settled` / `estimated` / `unknown` |
| settled cost | |
| temporary objects cleaned | |

不得记录 Prompt、模型输出、图片、Base64、向量、URL、密钥、Provider Workspace
ID、Authorization/Cookie 或供应商错误正文。

## 各能力的最小合成用例

- 文本：固定 JSON Schema，拒绝额外文本和字段。
- 分析：合成指标与合成证据，验证结构和引用。
- OCR：运行时生成无个人信息的小图；检查坐标与低置信度降级，随后删除。
- Embedding：两到三句合成文本；检查数量、顺序、1024 维和有限值，不写正式索引。
- 图片：无人物、品牌和版权元素的提示，只生成一张；下载验证后清理，不进入内容库。

北京和新加坡必须分别记录；一个地域、能力、模型或配置版本通过，均不能推断其他
组合通过。`contract_verified` 只表示合同样例通过，不表示内容质量、生产稳定性或
平台审核通过率，也不会自动改变全局 Catalog 的 `experimental` 状态。

## 取消、失败与未知结果

取消不代表未计费。明确未发送的失败才释放 reservation；超时、连接中断或供应商
结果无法确认时记录 `provider_outcome_unknown`，保留保守预算等待人工处理。图片
验收产生的临时对象必须进入受控清理；清理失败只记录对象标识和稳定错误码。
