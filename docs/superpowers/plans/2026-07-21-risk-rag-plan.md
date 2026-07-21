# RiskRAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 先实现确定性规则和可验证检索，再允许模型做语境判断。

**Goal:** 建立抖音/小红书隔离、公共/私有分层、具备来源等级/版本/审核/评估的风控知识库，并对标题、文案和封面文字输出可引用的辅助风险判断。

**Architecture:** 文档入库流水线负责抓取、解析、分块和待审核版本；当前扫描只查询对应平台的 `active` 文档；确定性规则先执行，RAG 后执行；LLM 只能基于检索片段生成 finding。pgvector 用于候选召回，元数据过滤在向量查询前强制应用。

**Tech Stack:** FastAPI、Celery、PostgreSQL/pgvector、对象存储、Pydantic、OCR/Embedding adapter、pytest。

**Global Constraints:** 公共库默认只接受 S1/S2 和明确授权资料；S5 不能独立触发高风险拦截。RAG 无有效证据必须返回 `NO_ACTIVE_RISK_EVIDENCE`，不能编造引用。网页变化只产生待审核版本。

## Task 1: 风控文档模型、来源等级和生命周期

**Files:**
- Create: `apps/api/app/modules/risk_rag/models.py`, `schemas.py`, `lifecycle.py`, `repository.py`
- Test: `apps/api/tests/risk_rag/test_lifecycle.py`, `test_source_policy.py`

1. 表驱动测试 S1—S5、公共/私有权限、`draft→parsed→pending_review→active→superseded/expired` 合法迁移和非法回退。
2. 建立 `risk_documents`、`risk_chunks`；保存平台、作用域、来源 URL、发布日期、生效日、访问时间、授权状态、审核者和版本链。
3. 只有 active 参与当前扫描；历史扫描能按旧版本追溯。
4. Commit: `feat: model governed risk knowledge lifecycle`

## Task 2: 安全入库、分块、Embedding 与版本更新

**Files:**
- Create: `apps/api/app/modules/risk_rag/ingestion.py`, `chunking.py`, `tasks.py`
- Test: `apps/api/tests/risk_rag/test_ingestion.py`, `test_version_update.py`

1. 测试文件/网页作为不可信数据、SSRF 防护、内容哈希去重、分块保留条款位置、任务重试幂等和页面变化产生 pending_review。
2. Embedding 行记录模型 ID/维度/版本；更换模型必须清空并重建对应索引，不能混合向量。
3. 原始文档放对象存储；版权不明材料不进入开源种子。
4. Commit: `feat: add review-first risk document ingestion`

## Task 3: 确定性规则引擎

**Files:**
- Create: `apps/api/app/modules/risk_rag/rules.py`, `rule_sets/douyin.yml`, `rule_sets/xiaohongshu.yml`
- Test: `apps/api/tests/risk_rag/test_rules.py`

1. 测试明确敏感词、联系方式、格式变体、大小写/空格/谐音归一化，且平台规则不串用。
2. 规则每次发布都有版本、证据文档 ID、严重度和适用范围；无有效依据的规则不能标高风险。
3. 团队规则可更严格但不能把官方禁止项改成允许。
4. Commit: `feat: implement versioned deterministic risk rules`

## Task 4: 平台隔离检索与可验证引用

**Files:**
- Create: `apps/api/app/modules/risk_rag/retrieval.py`, `citations.py`
- Test: `apps/api/tests/risk_rag/test_retrieval.py`, `test_citations.py`, `test_prompt_injection.py`

1. 固定语料测试查询前强制过滤 `workspace/public scope + platform + active + effective date + embedding version`；不同平台、失效和未审核文档召回数必须为 0。
2. 每个引用返回文档标题、来源等级、URL/私有文档 ID、版本、生效日期、chunk 位置和原文短摘录。
3. 模型引用不存在的 chunk、超出证据的结论或被文档注入指令时，扫描失败并记录安全诊断。
4. Commit: `feat: retrieve platform-scoped verifiable risk evidence`

## Task 5: 封面 OCR、风险扫描与复检

**Files:**
- Create: `apps/api/app/modules/risk_rag/scanner.py`, `scan_tasks.py`, `router.py`
- Create: `apps/web/src/components/risk/risk-report.tsx`
- Test: `apps/api/tests/risk_rag/test_scanner.py`

1. 输入由标题、文案、封面 OCR 区域组成；OCR 低置信度明确标注，不能伪装成确定命中。
2. 输出 `risk_type/severity/matched_content/region/evidence/citations/reason/suggestion`，并固定免责声明“辅助判断，不保证通过平台审核”。
3. 扫描节点支持录入后、生成后、发布前；修改后复检创建新 scan，旧结果不覆盖。
4. 无证据时只返回确定性规则结果和“未检索到有效规则”。
5. Commit: `feat: deliver cited multimodal risk scanning`

## Task 6: 评估集、回归门槛和反馈审核

**Files:**
- Create: `apps/api/app/modules/risk_rag/evaluation.py`, `feedback.py`
- Create: `apps/api/tests/fixtures/risk_eval/**`
- Test: `apps/api/tests/risk_rag/test_evaluation.py`, `test_feedback.py`

1. 两个平台各建脱敏评估集：明确违规、安全、边界、图片文字变体、历史案例；数据必须人工生成或获授权。
2. 输出高风险召回率、安全内容误报率、引用正确率、无依据结论比例和一致性；规则/Prompt/模型变更时 CI 执行固定 Mock 回归，真实模型评估作为发布前受控任务。
3. 用户反馈 `correct | false_positive | missed | outdated_rule | wrong_severity`，审核前不影响规则。
4. 在 ADR 中记录首批门槛及调整理由，不把未经验证指标作为宣传。
5. Commit: `test: add governed risk rag evaluation gates`

## Task 7: 管理后台和模块验收

**Files:**
- Create: `apps/web/src/app/workspaces/[workspaceId]/risk-knowledge/**`
- E2E: `tests/e2e/risk-rag.spec.ts`

1. 管理员可上传、解析、审核、生效、替代、失效和检查更新；编辑者只能扫描和反馈；查看者只读。
2. E2E 分别用抖音/小红书规则扫描同一句话，验证索引和引用分离；私有案例不泄露到另一工作区。
3. 运行：

```bash
uv run --project apps/api pytest tests/risk_rag -q
pnpm --filter e2e test risk-rag.spec.ts
```

预期：隔离、生命周期、引用和无证据降级全通过。Commit: `feat: complete risk rag administration and acceptance`
