# 发布前清单

- [ ] 已配置真实私有安全报告渠道（当前阻断）。
- [ ] `LICENSE`、依赖/资产许可盘点和 NOTICE 义务已人工复核。
- [ ] 当前树和完整 Git 历史秘密扫描为 clean。
- [ ] Python 与 Node 生产依赖审计完成；Critical/High 默认阻断。例外只是有 CVE、受影响版本、影响、缓解、责任人和未过期复核日期的审计记录，不会绕过 Trivy 或审计命令。
- [ ] API、Web 与最终 API/Web 镜像 SPDX SBOM 已生成、解析并上传。
- [ ] API/Web 最终镜像漏洞扫描完成；任何 Critical/High 结果阻断发布。
- [ ] Compose 中的 pgvector、Redis、MinIO 部署依赖已固定到复核过的 digest 并分别完成镜像扫描；当前 tag-only 配置不得作为可复现发布输入。
- [ ] Redis/MinIO 的再分发范围和许可证义务已经法务/维护者确认；确认前只作为用户自行拉取的部署依赖，不纳入本项目镜像发布包。
- [ ] 扩展 Chrome/Edge 包通过构建、权限、制品 allowlist 和动态代码检查。
- [ ] README Mock 快速开始在隔离环境通过，且未使用真实平台或模型。
- [ ] Playwright E2E 基础镜像使用已固定的 `v1.61.1-noble@sha256:5b8f294aff9041b7191c34a4bab3ac270157a28774d4b0660e9743297b697e48`，并已复核 tag↔digest 映射。
- [ ] 未将真实用户数据、凭据、Cookie、邀请码、私有知识或未授权资产纳入发布包。

通过本清单不等同于最终产品验收；真实模型、真实页面、非开发者测试和 Task 9 验收仍独立进行。
