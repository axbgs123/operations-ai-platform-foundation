# Style、Facts 与 Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 模型调用全部以 Mock contract test 起步，禁止先接真实计费 API。

**Goal:** 实现账号风格继承、可追溯事实资料、模型能力适配，以及受事实和风控约束的标题、文案和四种封面生成。

**Architecture:** `StyleFacts` 提供版本化风格与已确认事实；`Generation` 只消费不可变的 `GenerationContext`；模型供应商在 adapter 层，领域层只识别能力；所有生成异步执行并在保存前经历事实复检和 RiskRAG 门禁。

**Tech Stack:** FastAPI/Pydantic/Celery、S3、OCR/文档解析适配器、Pillow/Skia 或服务端 Canvas 排版；Next.js 编辑器；pytest/Vitest/视觉快照测试。

**Global Constraints:** 已确认事实 > 风控规则 > 风格 > 爆款结构。沿用风格默认开启但标题/文案/封面可分别关闭。L5 视觉推测不得成为面料、成分、价格、尺码、功效、认证、产地、安全承诺的确定事实。

## Task 1: 模型能力接口、密钥与 Mock Provider

**Files:**
- Create: `apps/api/app/modules/models/capabilities.py`, `adapters/base.py`, `adapters/mock.py`, `config_service.py`
- Test: `apps/api/tests/models/test_capabilities.py`, `test_secret_storage.py`, `test_mock_provider.py`

1. 失败测试覆盖文本、视觉、图片、Embedding 能力匹配；不具备能力的模型不能被选择；密钥加密保存、响应与日志不可见；Mock 输出可重复。
2. 接口：

```python
class ModelAdapter(Protocol):
    capabilities: frozenset[Capability]
    async def generate_structured(self, request: ModelRequest[T]) -> T: ...
```

3. 适配器状态为 `verified | experimental | community | incompatible`；首个真实 provider 在实现任务开始时根据当日官方 API 写 ADR 并锁定具体模型 ID，完整 contract suite 通过后才能标 `verified`。
4. 任务失败不自动切供应商；无配置时 AI 按钮返回可操作的配置提示，数据功能仍正常。
5. Commit: `feat: establish capability-aware model adapters`

## Task 2: 风格样本、档案提取和版本继承

**Files:**
- Create: `apps/api/app/modules/style_facts/style_models.py`, `style_service.py`, `style_tasks.py`
- Create: `apps/web/src/app/workspaces/[workspaceId]/styles/**`
- Test: `apps/api/tests/style_facts/test_style_profiles.py`, `test_style_inheritance.py`

1. 测试只有用户人工选择的已发布内容可作为样本；爆款不自动成为风格；账号/栏目版本继承和到期恢复；三个风格开关关闭后 context 中不存在对应历史信息。
2. 档案结构包含设计文档第 11 节的标题、文案、封面字段和禁止项；每次更新生成不可变版本。
3. UI 展示样本来源、提取结果和差异，用户确认后才生效；提供“一键沿用全部风格”和三个独立开关。
4. Commit: `feat: add explicit versioned account style profiles`

## Task 3: 事实来源上传、解析与 SSRF 防护

**Files:**
- Create: `apps/api/app/modules/style_facts/fact_models.py`, `source_ingestion.py`, `url_safety.py`, `fact_tasks.py`
- Create: `apps/web/src/app/workspaces/[workspaceId]/facts/**`
- Test: `apps/api/tests/style_facts/test_fact_sources.py`, `test_url_safety.py`

1. 测试文档、图片、链接、文字和联网来源；文件类型/大小；URL 禁止 loopback、私网、链路本地、云元数据、DNS rebinding 和非 HTTP(S)；上传内容不能覆盖系统指令。
2. 建立 `fact_sources`、`fact_items`，保存 L1—L5、来源位置、置信度、确认/冲突/覆盖记录。
3. 解析结果只是候选；确认 API 必须记录成员和时间。未上传资料允许继续但返回醒目 `unconstrained_facts=true`。
4. Commit: `feat: ingest traceable fact sources safely`

## Task 4: 事实冲突、等级与禁止推测规则

**Files:**
- Create: `apps/api/app/modules/style_facts/fact_policy.py`, `fact_verification.py`
- Test: `apps/api/tests/style_facts/test_fact_priority.py`, `test_visual_prohibitions.py`, `test_conflicts.py`

1. 表驱动测试锁定 L1—L5 优先级、过期检查、同级冲突暂停、低级不可覆盖高级、人工强制覆盖需理由。
2. 为禁止视觉推测字段建立代码枚举，不只写 Prompt；L5 命中这些字段一律 `candidate_only`。
3. 生成前有未解决冲突返回 `FACT_CONFLICT`；生成后逐条 claim 与已确认事实比对，高风险冲突阻止进入待发布。
4. Commit: `feat: enforce deterministic fact safety policy`

## Task 5: 爆款引用与不可变 GenerationContext

**Files:**
- Create: `apps/api/app/modules/generation/context.py`, `schemas.py`
- Test: `apps/api/tests/generation/test_context.py`

1. 测试只能选择 0—3 条同工作区/平台/账号且已人工确认的爆款；不同账号和未确认候选拒绝。
2. `GenerationContext` 固定账号、栏目、目标、已确认事实版本、风格版本/开关、爆款引用、用户提示词、资料资产、风险规则版本和模型配置。
3. 上下文生成后不可修改；重试复用原 context，用户修改输入则创建新 run。
4. Commit: `feat: build immutable generation context`

## Task 6: 标题与文案生成、编辑和采用状态

**Files:**
- Create: `apps/api/app/modules/generation/text_service.py`, `tasks.py`, `router.py`
- Create: `apps/web/src/app/workspaces/[workspaceId]/generation/page.tsx`, `text-editor.tsx`
- Test: `apps/api/tests/generation/test_text_generation.py`, `test_generation_cache.py`

1. Mock contract 测试多个标题、一份文案、结构化引用、无资料提示、事实复检、缓存、取消/重试和不可用模型降级。
2. 用户提示词是数据，不得覆盖事实/风控；风格和爆款均不得引入未确认事实。
3. 保存生成原稿、人工最终稿、采用/放弃状态和修改幅度；禁止把完整敏感文案写日志。
4. Commit: `feat: generate fact-grounded titles and copy`

## Task 7: 四种封面模式与准确中文排版

**Files:**
- Create: `apps/api/app/modules/generation/cover_models.py`, `cover_service.py`, `layout.py`
- Create: `apps/web/src/components/generation/cover-editor/**`
- Test: `apps/api/tests/generation/test_cover_modes.py`, `test_layout.py`
- Fixture: `apps/api/tests/fixtures/golden-covers/**`

1. 测试模板/AI 视觉/混合/自定义四种模式；所有模式支持 prompt、参考图和用途；产品/人物保留规则；尺寸与文字安全区。
2. 图片模型只输出背景/主体，程序叠加最终中文、Logo 和品牌元素；布局测试验证不越界、不裁字、文本内容精确。
3. 参考图用途严格枚举 `composition | style | person | product | palette`；上传前显示发送给模型的数据提示。
4. 黄金图允许小范围像素差；人工检查主尺寸 1080×1440、1080×1920、1080×1080。
5. Commit: `feat: deliver four-mode deterministic cover generation`

## Task 8: 生成预设、任务状态与发布门禁

**Files:**
- Create: `apps/api/app/modules/generation/presets.py`, `publication_gate.py`
- Create: `apps/web/src/components/generation/task-status.tsx`
- Test: `apps/api/tests/generation/test_presets.py`, `test_publication_gate.py`
- E2E: `tests/e2e/generation.spec.ts`

1. 预设保存模型、尺寸、参数、参考图用途、文字区、品牌元素和版本，不保存密钥。
2. 门禁顺序固定：结构验证→事实复检→RiskRAG 扫描→允许保存草稿；高风险事实冲突禁止待发布；风控结果按风险计划规则处理。
3. E2E：选择账号/栏目→上传服装资料→确认面料→默认沿用风格→引用已确认爆款→生成→编辑→复检→保存草稿。
4. 运行主计划 Gate A 和 `pnpm --filter e2e test generation.spec.ts`；预期无资料与有冲突两条降级路径均可解释。
5. Commit: `feat: complete governed generation workflow`
