# 热点榜截图与模型原生联网实施计划

## Task 1：模型原生联网合同与千问适配

- 增加配置版本绑定的原生联网检测状态。
- 实现统一 `NativeWebSearchProvider` 合同和严格来源 Schema。
- 实现千问 Responses API `web_search`/`web_extractor` 适配器。
- 增加管理员受控检测 API；Mock 不访问外网。
- OpenAI-compatible 第一版明确 not_adapted。

## Task 2：热点暂存、OCR 与人工确认

- 新增工作区隔离的热点采集任务与不可变热点快照。
- 复用对象存储、视觉/OCR 和任务 fencing。
- 增加热点结构化候选、修正、排除和确认 API。
- 保留来源、时间、完整度和 OCR 降级状态。

## Task 3：扩展热点采集模式

- 使用 activeTab+scripting 在用户手势下采集当前公开页面。
- 不新增 `<all_urls>`、cookies、webRequest 等权限。
- 增加“运营数据/热点榜”采集用途选择。
- 上传后跳转热点确认页。

## Task 4：热点研究、智能体与生成门禁

- 新增只读热点与研究工具。
- 仅允许已确认热点调用已验证的原生联网适配器。
- 保存可验证来源并生成账号匹配、选题、标题和文案候选。
- 接入现有事实、风格、爆款和 RiskRAG。

## Task 5：工作台页面与验收

- 在创作分类增加“热点创作”入口。
- 完成采集历史、确认、研究、生成和来源展示。
- 覆盖 Admin/Editor/Viewer、移动端、跨工作区和 Mock E2E。
- 更新 OpenAPI、生成类型、迁移、部署和开源文档。
