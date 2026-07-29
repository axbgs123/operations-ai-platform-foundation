# 部署与运维

本地 Mock 部署按照[README](../../README.md)执行：复制 `.env.example`，保持 `APP_MOCK_MODE=true`，以 `--profile demo` 启动并访问 `/demo`。此模式不要求外部模型密钥，也不会访问抖音、小红书或任何真实模型服务。

生产前必须替换所有 `local-development-only` 与 `change-me` 高熵密钥：PostgreSQL 密码、S3 凭据、存储签名密钥、模型密钥加密密钥和会话签名密钥。使用专用私有网络的 PostgreSQL、认证 Redis 与私有 S3 bucket；数据服务不应公开端口。API、Worker、Web 保持非 root、只读文件系统、drop capabilities，并通过 HTTPS 反向代理暴露最少端口。

千问凭据不通过环境变量、命令行或 Compose 文件传入；管理员只能在工作区模型设置页
提交，由服务端使用部署时的模型密钥加密主密钥加密保存。北京与新加坡的 Provider
Workspace ID 和凭据不可混用。启用真实调用前还必须为每个 capability 明确配置
工作区预算；无政策、Redis 不可用或预算不足时均 fail-closed。完整操作边界见
[千问配置与用量治理](qianwen-model-configuration.md)。

启动顺序是 Postgres/Redis/S3 健康 → 独立 `migrate` → `bucket-init` → 可选 `demo-seed` → API/Worker → Web。不要让多个 Web worker 竞争迁移。升级前备份并记录镜像/数据库版本；先在隔离环境运行迁移，失败按数据库和镜像兼容性计划回滚。`/health/live` 只表示进程存活，`/health/ready` 还检查依赖可用性。

常见故障：readiness 失败时先检查迁移、bucket、数据库/Redis/S3 连通性；Demo 缺失时确认 profile 与 `DEMO_SEED_ENABLED`；生产默认值被拒绝时替换高熵密钥。E2E 基础镜像固定为 Playwright `v1.61.1-noble` 的已审计 digest `sha256:5b8f294aff9041b7191c34a4bab3ac270157a28774d4b0660e9743297b697e48`；重建时仍须核对 tag 与 digest 的映射。
