# 许可证决定：Apache-2.0

本仓库的原创源代码与原创文档采用 Apache-2.0；完整文本见根目录
[LICENSE](../../LICENSE)。这只覆盖本仓库的原创材料，不会改变依赖、镜像、字体或用户导入内容的许可证。每次发布都必须以锁文件、SBOM 和镜像扫描结果复核以下台账；`NOASSERTION` 的传递项不能被误写成“Apache 兼容”。

## 直接生产依赖

| 范围 | 名称与当前声明版本 | 上游许可证 | Apache-2.0 发布处理 |
| --- | --- | --- | --- |
| API | Alembic `>=1.16,<2` → `1.18.5`；FastAPI `>=0.139.2` → `0.139.2`；Pydantic Settings `>=2.10,<3` → `2.14.2`；OpenPyXL `>=3.1,<4` → `3.1.5`；pgvector `>=0.4,<1` → `0.5.0` | MIT、MIT、MIT、MIT、MIT | 可与本仓库许可并存；保留上游通知。 |
| API | Argon2-cffi `>=25.1,<26` → `25.1.0`；Celery `>=5.6,<5.7` → `5.6.3`；cryptography `>=48.0.1,<49` → `48.0.1`；Pillow `>=11,<13` → `12.3.0`；PyPDF `>=5,<7` → `6.14.2`；SQLAlchemy `>=2.0,<2.1` → `2.0.51` | MIT、BSD-3-Clause、Apache-2.0-or-BSD-3-Clause、HPND、BSD-3-Clause、MIT | 可并存；镜像/SBOM 仍必须保存实际锁定版本与通知。 |
| API | Psycopg binary `>=3.2,<4` → `3.3.4` | LGPL-3.0-only（及二进制随附组件的各自条款） | 不把 LGPL 代码再授权为 Apache；发布镜像须保留许可证、来源/替换义务和二进制组件通知。 |
| Web | Next `16.2.11`、React/React DOM `19.2.4`、`@operations-ai/shared-schemas` `0.1.0` | MIT、MIT、自有 Apache-2.0 | 可并存；共享包的生产传递依赖 `openapi-fetch 0.15.0`（MIT）列入扩展/Web SBOM。 |
| Web | ECharts `^6.1.0`（锁文件决定最终版本） | Apache-2.0 | 保留 NOTICE/许可证；不得仅依据范围符号声明最终版本。 |
| 扩展 | `@operations-ai/shared-schemas` `workspace:*` | 自有 Apache-2.0 | 打包时解析为工作区 `0.1.0`，并把其 `openapi-fetch 0.15.0` 作为生产传递依赖写入扩展 SPDX。 |

`pnpm-workspace.yaml` 当前把 Next 的运行时可选依赖 Sharp 固定为 `0.35.0`，并把
PostCSS 固定为 `8.5.20`。这是为消除生产审计中的已知 High 漏洞而设置的最小覆盖，
不是许可证例外；两者仍按各自 Apache-2.0 / MIT 条款进入 Web SBOM。Next 上游携带
不低于这些安全版本后，应重新评估并移除覆盖，不能让覆盖长期掩盖上游约束变化。

## 镜像、服务与字体

| 项目/版本 | 主要许可证或条款 | 分发结论 |
| --- | --- | --- |
| API 基础 `python:3.12-alpine@sha256:6d43…419df` | Python PSF-2.0，Alpine 包各自许可 | 最终 API 镜像必须随 SBOM/NOTICE 复核 Alpine 组件，不以本仓库 LICENSE 覆盖。 |
| Web 基础 `node:22-alpine@sha256:16e…30c3e2` | Node.js MIT；Alpine 包各自许可 | 最终 Web 镜像必须保留镜像与 apk 组件的许可台账。 |
| `pgvector/pgvector:0.8.2-pg18-trixie` | PostgreSQL License（PostgreSQL/pgvector 组件仍以镜像 SBOM 为准） | 服务镜像与源码发布分离；对外分发镜像须附带通知。 |
| `redis:8.2.1-alpine` | Redis 8 三选一：RSALv2、SSPLv1、AGPLv3 | 这是 copyleft/商业条款决策点；未选定合规路径并完成通知/源码义务前，不得把该镜像作为公开分发包。 |
| `minio/minio:RELEASE.2025-04-22T22-12-26Z` | AGPLv3 | 网络服务与镜像分发都需法务确认 AGPLv3 义务；不能用 Apache-2.0 声明替代。 |
| `mcr.microsoft.com/playwright:v1.61.1-noble` | Playwright Apache-2.0，浏览器/系统组件各自条款 | 仅用于 E2E 构建镜像；若对外分发，固定其已核验 digest `sha256:5b8f…697e48` 并审计浏览器条款。 |
| `font-noto-cjk`（API Dockerfile） | SIL Open Font License 1.1 | 字体被放入 API 镜像，发布镜像时必须随附 OFL 许可/通知。 |

Syft `v1.44.0`、Trivy `0.69.3` 与 Gitleaks `v8.28.0` 在 CI 固定到 manifest digest；版本与 digest 的完整映射见[供应链安全](supply-chain-security.md)。任何新增直接依赖、镜像或字体都必须更新此文档、锁文件和 SPDX，并接受许可证审查。
