# 供应链安全

CI 使用最小 `contents: read` 权限；所有 GitHub Action 固定到不可变 SHA。Fork PR 不获得秘密，CI 不配置模型/OCR/Embedding 真实凭据，也不访问真实抖音或小红书页面。

## 发布门

* `scripts/secret-scan.sh` 检查受跟踪、未跟踪（包括被 `.gitignore` 排除的 `.env*`）和全部可达 Git 历史；它只输出通过/失败状态，绝不回显匹配内容。CI 另以固定 digest 的 Gitleaks 做独立历史扫描并启用 `--redact`。
* `verify-source-release` 对暂存目录递归执行精确顶层 allowlist，并拒绝 `.env*`（仅 `.env.example` 例外）、SQL/dump/backup/DB、key/cert、私有资料、默认忽略目录和符号链接。
* `generate-sbom` 只生成 API/Web **锁文件依赖清单**，覆盖锁定的传递包；它不声称覆盖镜像。构建完成后 Syft 才对最终 API/Web 镜像生成独立 SPDX。扩展包生成自己的生产运行时 SPDX。
* 所有 SPDX JSON 先经项目结构门，再用固定 `spdx-tools==0.8.3` 的 `pyspdxtools -i` 解析；JSON 能 parse 并不等于 SPDX 合格。
* Node 用 `pnpm audit --prod`；Python 用固定 `pip-audit==2.9.0`。最终 API/Web 镜像由 Trivy 对 Critical/High 阻断。扩展 zip 逐文件 allowlist、哈希清单和 SPDX 均须通过。
* 文档门递归解析全部发布 Markdown 的本地链接/图片，校验链接不逃逸仓库，并检查所有被引用 PNG 的 chunk/CRC/IHDR/IEND 结构。Demo PNG 还必须匹配相邻的合成 `/demo` 捕获 provenance（文件名、SHA-256、模式、路由）；CI 的 Playwright 测试先断言合成 UI 文本，再真实渲染并保存审计截图。它不访问或宣称验证真实平台页面。

## 固定工具镜像

以下是已核验的多架构 manifest-list digest；CI 使用 `image@sha256` 而非浮动 tag，注释保留 tag 便于审计。

| 工具 | 已审计 tag | digest |
| --- | --- | --- |
| Syft | `v1.44.0` | `sha256:86fde6445b483d902fe011dd9f68c4987dd94e07da1e9edc004e3c2422650de6` |
| Trivy | `0.69.3` | `sha256:bcc376de8d77cfe086a917230e818dc9f8528e3c852f7b1aff648949b6258d1c` |
| Gitleaks | `v8.28.0` | `sha256:cdbb7c955abce02001a9f6c9f602fb195b7fadc1e812065883f695d1eeaba854` |
| Playwright E2E 基础（若重新构建/分发） | `v1.61.1-noble` | `sha256:5b8f294aff9041b7191c34a4bab3ac270157a28774d4b0660e9743297b697e48` |

API/Web/E2E Dockerfile 的基础镜像均使用 digest；重建时仍须验证上表 tag 与 digest 的对应关系。
Compose 中的 pgvector、Redis、MinIO 当前是 tag-only 的外部部署依赖，不属于本 Task
生成的 API/Web 镜像发布物，也不得被描述为已扫描或可复现。公开分发完整 Compose
部署包前，必须为三者固定已复核 digest、生成/验证镜像 SBOM 并执行 Critical/High
扫描；Redis/MinIO 还必须先完成下述许可证分发决策。

临时不能修复的上游漏洞不得静默忽略。必须在 `.github/security-exceptions.yml` 记录 CVE、受影响版本、影响、缓解、责任人和复核日期；未知字段、空字段、无效/过期日期均阻断发布。例外只是受审计记录，不能自动放宽 Critical/High 门。缺失真实安全邮箱、未确认资产/许可证、任何未固定的发布镜像、秘密扫描失败、SBOM/镜像扫描失败或 allowlist 失败，均为发布阻断项。
