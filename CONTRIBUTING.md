# 贡献指南

感谢贡献。请使用 Node 22、pnpm 11、Python 3.12 与 Docker Compose v2；先执行 `pnpm install --frozen-lockfile` 和 `uv sync --project apps/api --frozen`。不要提交真实运营数据、平台 Cookie、密码、邀请码、令牌、模型密钥、私有 Prompt 或未授权素材；测试数据必须是人工合成或有明确书面授权。

从 `codex/` 前缀的短分支提交小而可审阅的改动，使用 Conventional Commit 风格。PR 必须说明风险、测试证据和是否修改公开接口。AI 可协助实现，但贡献者仍需负责需求理解、业务判断、测试验收和最终决定，并在 PR 中如实披露 AI 协助范围。

数据库迁移只能新增，绝不修改已发布历史迁移；在隔离临时数据库验证。OpenAPI 改动后运行 `pnpm schemas:generate`，随后运行 `pnpm schemas:check`；平台指标元数据变更后运行 `pnpm metrics:generate` 与 `pnpm metrics:check`。

提交前至少运行：

```bash
pnpm lint && pnpm typecheck && pnpm test
uv run --project apps/api ruff check .
uv run --project apps/api mypy app
uv run --project apps/api pytest
docker compose -f infra/docker/compose.yml config --quiet
```

PR 清单：范围明确、测试为合成数据、无秘密/私人数据、无未审计依赖或资产、文档与生成物同步、工作区/平台隔离不被削弱。详见[安全政策](SECURITY.md)。
