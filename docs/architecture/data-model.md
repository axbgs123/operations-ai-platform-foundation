# 数据模型与隔离

核心层级是 `Workspace → Member/Invitation → PlatformAccount → Content → Snapshot/Metric`。每个业务记录带 `workspace_id`，资源命中但上下文不一致时按不存在处理；抖音与小红书的指标、基准、风控索引与账号配置不混用。

- Workspace、Member、Invitation：角色、访问码强哈希、会话和审计；原邀请码、会话和令牌不可导出。
- PlatformAccount、Content、Snapshot、Metric：内容版本、发布状态、快照与平台指标；快照是不可变历史，重复导入由幂等键合并。
- Analysis、Suggestion、Style、Fact、Generation：输入证据、Prompt/模型/风格版本、事实确认和生成复检可追溯。
- RiskRAG：文档、分段、来源等级、平台、审核/生效版本、扫描与发现；向量不作为可移植备份的一部分。
- Capture Extension：临时截图采集、页面版本、确认状态、有限期令牌；不会保存 Cookie、密码或邀请码。
- Export、Restore、Retention、Operations、Analytics：版本化导出、恢复预览、补偿任务、软删除/保留、后台任务、最少事件字段。

软删除保留恢复窗口，最终删除才清理结构化记录、向量和对象。对象引用与数据库提交通过暂存和补偿保持一致；恢复前有版本栅栏、校验和、冲突预览，失败不改变原工作区。禁止导出的字段包括密钥密文、邀请码哈希/原码、会话/令牌、密码、向量、媒体正文和未经授权的私有知识正文。
