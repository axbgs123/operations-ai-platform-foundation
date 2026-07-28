# 导出、备份与恢复

CSV 用于表格分析，Markdown 用于单条可读分析报告，JSON 用于轻量结构化迁移，ZIP 用于完整工作区备份。JSON 不含媒体、密钥、会话、令牌、邀请码、哈希或向量；ZIP 固定包含 `manifest.json`、`data.json`、`assets/`、`knowledge/` 与 `checksums.json`，每一文件以 SHA-256 校验。

恢复先在隔离暂存区解包，拒绝 Zip Slip、超大压缩、缺失或篡改；随后校验 schema/product 版本、对象引用和冲突。预览将标记 create、overwrite、skip 与 conflict。用户选择新工作区或合并；提交失败走事务回滚/对象补偿，`configuration_required` 表示需先补足本地配置。向量不直接恢复，恢复后按当前 Embedding 配置重建。

恢复前先另行备份，并在隔离环境演练。工作区删除与保留不同：删除可经过软删除/恢复窗口，最终删除才清理结构化数据、向量和对象；备份不会绕过保留政策或权限。
