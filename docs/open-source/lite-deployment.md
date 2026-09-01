# 轻量部署

轻量版面向个人作品演示、个人运营和低并发小团队。它保留账号、内容、数据导入、分析、策略资产、AI 创作、运营智能体、发布前检查、模型配置、浏览器扩展和数据导出，默认只运行三个常驻容器：

| 服务 | 用途 | 内存上限 |
| --- | --- | ---: |
| PostgreSQL/pgvector | 结构化数据及现有检索字段 | 384 MiB |
| FastAPI | API、同步任务、本地文件访问 | 640 MiB |
| Next.js | Web 工作台 | 256 MiB |

在隔离的 macOS Docker Desktop 环境完成创建团队、恢复会话、创建账号、创建内容、上传并下载本地文件后，三个容器合计约使用 **279 MiB**。该数值不含 Docker Desktop 虚拟机及宿主系统开销，也不是高并发承载保证。2 核 2 GB 服务器适合单人或少量成员低频使用；建议配置交换空间，并避免多人同时执行图片 OCR、封面生成或大批量导入。

## 与完整版的区别

轻量版不运行 Redis、MinIO 和独立 Worker。任务由 API 进程同步执行，对象写入受控本地 Docker 卷。以下高级入口不在轻量 API 中开放：

- ZIP 完整恢复、恢复补偿和工作区彻底删除；
- 风控知识文档治理、反馈审核和评估后台；
- 产品北极星指标与模型费用预算治理；
- 面向多 Worker 的任务租约、死信和运维操作后台。

界面仍保留运营必需的内容风险扫描，但不展示风控知识治理后台。轻量版保留工作区隔离、成员角色、会话与 CSRF、模型密钥加密、上传路径/类型/大小检查、SSRF 防护和基本限流。

## 启动

```bash
cp .env.example .env
docker compose -f infra/docker/compose.lite.yml config --quiet
docker compose -f infra/docker/compose.lite.yml build api
docker compose -f infra/docker/compose.lite.yml build web
docker compose -f infra/docker/compose.lite.yml up -d --no-build
curl --fail http://127.0.0.1:8000/health/ready
```

打开 `http://127.0.0.1:3000/enter` 创建团队。正常停止但保留数据：

```bash
docker compose -f infra/docker/compose.lite.yml down
```

只有确认不再需要本地数据时，才使用 `down --volumes`。

## 什么时候升级完整版

出现下列任一情况时，再考虑启用完整版：多人持续并发生成；任务必须在 API 重启后自动续跑；需要独立 S3 对象存储；需要高级恢复、删除审计、风控知识治理或生产级任务运维。不要仅因为“架构更完整”而提前承担这些常驻资源和维护成本。
