# Qianwen Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现有 Mock 默认模式和业务安全门禁的前提下，为工作区提供按能力、地域、明确模型快照隔离的千问真实模型接入。

**Architecture:** 现有 `ModelConfig` 继续负责工作区级加密配置；服务端固定 `ProviderCatalogEntry`，客户端只能选择 Catalog 已声明的能力和状态。各千问 Adapter 通过百炼 OpenAI 兼容 HTTP 合同调用，端点仅由受控地域和 Provider Workspace ID 构造；业务服务只消费现有能力接口，不接触 API Key、任意 URL 或供应商响应正文。

**Tech Stack:** FastAPI、Pydantic v2、SQLAlchemy/Alembic、`httpx` AsyncClient/MockTransport、PostgreSQL、Celery、Next.js、pytest/Vitest/Playwright。

## Global Constraints

- 文本基线固定为 `qwen3.5-plus-2026-04-20`；不得使用 `latest`、稳定别名或客户端自报 verified。
- 千问真实调用在 Task 6 受控验收前均为 `experimental`；普通 CI 只使用 Mock/Fake Transport，不访问外网、不产生费用。
- 端点只能由 `cn-beijing | ap-southeast-1` 与严格的 `llm-[a-z0-9]+` Provider Workspace ID 构造；不得接收完整 `base_url`。
- 密钥只在执行一次具体模型调用时解密，不进入响应、日志、异常、任务参数、导出、备份或产品事件。
- Provider 失败不得自动切换 Mock 或其他 Provider；只有 429、超时和 5xx 最多重试一次，总尝试不超过两次。
- 工作区、平台、账号、模型版本和 Embedding 版本必须显式隔离；已知资源跨工作区访问统一返回 404。
- 不修改整体视觉风格、导航结构或页面布局；UI 只增加模型配置、状态、费用/数据发送提示所需的最小控件。
- 不使用真实用户数据、真实私有案例、未经授权平台规则、真实页面自动化或对话中提供的 API Key。
- 任何迁移只新增版本文件，不修改 `20260727_0027` 及以前迁移；数据库验证只使用自动清理的临时 schema/容器。

---

### Task 1: 千问 Provider 基础、配置和结构化文本 Adapter

**Files:**
- Create: `docs/architecture/0003-qianwen-provider-contract.md`
- Create: `apps/api/app/modules/models/catalog.py`
- Create: `apps/api/app/modules/models/adapters/qianwen.py`
- Create: `apps/api/tests/models/test_qianwen_catalog.py`
- Create: `apps/api/tests/models/test_qianwen_config.py`
- Create: `apps/api/tests/models/test_qianwen_provider.py`
- Create: `apps/api/migrations/versions/20260728_0028_qianwen_model_config.py`
- Create: `.superpowers/sdd/2026-07-28-qianwen-provider-plan/task-1-report.md`
- Modify: `apps/api/app/modules/models/models.py`
- Modify: `apps/api/app/modules/models/config_service.py`
- Modify: `apps/api/app/modules/models/router.py`
- Modify: `apps/api/app/modules/models/adapters/__init__.py`
- Modify: `apps/api/app/core/logging.py`
- Modify: `apps/api/pyproject.toml`
- Modify: `apps/api/uv.lock`
- Modify: `apps/api/tests/models/test_secret_storage.py`
- Modify: `apps/api/tests/exports/test_json_backup.py`
- Modify: `apps/api/tests/exports/test_zip_backup.py`
- Modify: `apps/api/tests/workspace/test_migrations.py`
- Modify: `docs/architecture/model-adapters.md`
- Regenerate: `packages/shared-schemas/openapi.json`
- Regenerate: `packages/shared-schemas/src/schema.ts`

**Interfaces:**
- Produces: `QianwenRegion`, `ProviderProtocol`, `ProviderCatalogEntry`, `QIANWEN_TEXT_MODEL_ID`, `get_catalog_entry(provider: str, model_id: str) -> ProviderCatalogEntry`.
- Produces: `build_qianwen_endpoint(region: QianwenRegion, provider_workspace_id: str) -> str`.
- Produces: `QianwenProvider.generate_structured(request: ModelRequest[T]) -> T`.
- Produces: `ModelProviderError(code: ModelErrorCode, provider_request_id: str | None = None)` with stable safe codes.
- Extends: `ModelConfig` with nullable `region` and encrypted-at-rest/private `provider_workspace_id`; both are mandatory for Qianwen.
- Consumes later: Task 2 creates a `QianwenProvider` only after `ModelConfigService` resolves the current workspace config and decrypts its key for that call.

- [ ] **Step 1: Record the official contract**

  In the ADR record the 2026-07-28 check date and official Alibaba Cloud Model Studio links for OpenAI-compatible Chat Completions, `qwen3.5-plus-2026-04-20`, structured output, error codes and rate limits. State these exact endpoint templates:

  ```text
  https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions
  https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1/chat/completions
  ```

  Record `response_format={"type":"json_object"}`, top-level `enable_thinking=false`, non-streaming calls, `experimental` status, maximum two attempts and the absence of real API evidence.

- [ ] **Step 2: Write Catalog and endpoint RED tests**

  Test exact TEXT-only Catalog fields, both endpoints, unknown region rejection, `llm-[a-z0-9]{4,64}` validation, rejection of dots/slashes/uppercase/IP/localhost/credentials/fragments, unknown model rejection, non-Catalog verified rejection and client capability expansion rejection.

- [ ] **Step 3: Run Catalog RED**

  Run:

  ```bash
  apps/api/.venv/bin/python -m pytest \
    apps/api/tests/models/test_qianwen_catalog.py \
    apps/api/tests/models/test_qianwen_config.py -q
  ```

  Expected: collection/import failures for missing `catalog.py`, missing Qianwen fields and missing endpoint builder.

- [ ] **Step 4: Implement the minimum Catalog and persisted configuration**

  Implement frozen strict schemas equivalent to:

  ```python
  class ProviderCatalogEntry(BaseModel):
      model_config = ConfigDict(extra="forbid", frozen=True)
      provider: Literal["qianwen"]
      model_id: Literal["qwen3.5-plus-2026-04-20"]
      capabilities: frozenset[Capability]
      protocol: Literal["openai_chat_completions"]
      available_regions: frozenset[QianwenRegion]
      adapter_status: Literal[AdapterStatus.EXPERIMENTAL]
      structured_output_support: Literal[True]
      thinking_mode: Literal["disabled_for_structured_output"]
      contract_version: Literal["qianwen-chat-json-v1"]
  ```

  `ModelConfigService.save` must derive Qianwen capabilities/status from the Catalog and reject mismatched client claims. It must store the Provider Workspace ID without returning it through `ModelConfigRead`; list/select responses may expose only region and non-secret Catalog metadata.

- [ ] **Step 5: Add migration RED/GREEN**

  Add nullable `region VARCHAR(32)` and `provider_workspace_id VARCHAR(80)` columns so existing Mock records remain valid. Add a constraint requiring both fields together for `provider='qianwen'`, update model metadata/schema consistency expectations, and prove empty PostgreSQL upgrades from base to `20260728_0028`.

- [ ] **Step 6: Write structured Adapter RED tests**

  With `httpx.MockTransport`, assert Authorization header use, exact endpoint, model snapshot, fixed system policy, user prompt/inputs in an untrusted-data envelope, JSON instruction, `response_format`, `enable_thinking=false`, non-streaming request and strict Pydantic output. Add separate RED cases for empty content, Markdown fences, leading/trailing explanation, truncated JSON, wrong field type, `finish_reason=length`, malformed envelope and missing choices.

- [ ] **Step 7: Write retry/error/logging RED tests**

  Assert 401/403/ordinary 4xx make one attempt; 429/timeout/500/503 make at most two; success after one retry returns normally. Assert stable codes:

  ```text
  MODEL_AUTHENTICATION_FAILED
  MODEL_RATE_LIMITED
  MODEL_TIMEOUT
  MODEL_INVALID_RESPONSE
  MODEL_PROVIDER_UNAVAILABLE
  MODEL_CAPABILITY_UNAVAILABLE
  ```

  Verify exceptions/responses/logs never contain API Key, prompt, inputs or output; successful and failed calls log only provider, model ID, provider request ID, token usage, latency, attempt and safe error code.

- [ ] **Step 8: Run Adapter RED**

  Run:

  ```bash
  apps/api/.venv/bin/python -m pytest \
    apps/api/tests/models/test_qianwen_provider.py -q
  ```

  Expected: failures because `QianwenProvider`, strict response validation, retry mapping and safe telemetry do not exist.

- [ ] **Step 9: Implement the minimum Adapter**

  Declare `httpx>=0.28,<1` as a direct runtime dependency and remove the unnecessary `httpx2` development dependency. Construct `httpx.AsyncClient` with injected transport, fixed timeout, `follow_redirects=False`, `trust_env=False`; never accept a caller URL. Parse `choices[0].message.content` with one `json.loads`, then call `response_model.model_validate(payload, strict=True)` without fence stripping, extraction, coercion or repair.

- [ ] **Step 10: Prove permission, isolation and backup boundaries**

  Extend API/service tests for admin success, editor/viewer mutation 403, cross-workspace 404, encrypted key at rest, no key/provider workspace ID in responses, no global `DASHSCOPE_API_KEY` fallback and no Mock fallback. Extend JSON/ZIP tests so `api_key`, ciphertext, Provider Workspace ID and temporary provider URLs are absent.

- [ ] **Step 11: Synchronize contracts and documentation**

  Regenerate OpenAPI and TypeScript types using repository scripts; do not hand-edit generated types. Update `model-adapters.md` to distinguish engineering-contract coverage from real-provider verification.

- [ ] **Step 12: Run Task 1 verification**

  Run the Task 1/model suites, API full pytest, Ruff, Mypy, Web tests, TypeScript, OpenAPI/platform-metrics drift, empty temporary database migration, Alembic check, schema consistency, Compose config, current-tree secret scan, `git diff --check`, fixed Python production audit, source SBOM generation/validation and Mock fresh-install regression. Clean all temporary containers/schemas/volumes.

- [ ] **Step 13: Write report and commit**

  Record RED→GREEN evidence, official links/model snapshot, Catalog, endpoint safety, migration/OpenAPI details, all commands/results, no real call/no cost, cleanup and Git/remote status. Commit only Task 1:

  ```bash
  git commit -m "feat: add qianwen structured text provider"
  ```

  Stop immediately; do not start Tasks 2–6 or the original Task 9.

---

### Task 2: 标题文案生成与运营分析接入

**Files:**
- Create: `apps/api/app/modules/models/adapters/qianwen_text_generation.py`
- Create: `apps/api/app/modules/models/adapters/qianwen_analysis.py`
- Create: `apps/api/tests/models/test_qianwen_text_generation.py`
- Create: `apps/api/tests/models/test_qianwen_analysis.py`
- Modify: `apps/api/app/modules/generation/text_service.py`
- Modify: `apps/api/app/modules/analysis/schemas.py`
- Modify: `apps/api/app/modules/analysis/tasks.py`
- Modify: `apps/api/app/modules/models/config_service.py`

**Interfaces:**
- Consumes: Task 1 `QianwenProvider.generate_structured`, TEXT Catalog entry and workspace-scoped adapter factory.
- Produces: `QianwenTextGenerationAdapter.generate(TextGenerationRequest) -> GeneratedTextDraft`.
- Produces: `QianwenAnalysisAdapter.analyze(AnalysisEvidenceBundle) -> AnalysisReport`.

- [ ] **Step 1: Write RED contract tests** proving generation and analysis select only the current workspace TEXT config, preserve facts/risk/evidence policies, reject unknown citations and never send cover URLs in this text-only task.
- [ ] **Step 2: Run RED** and confirm both business paths still choose Mock/unavailable behavior instead of Qianwen.
- [ ] **Step 3: Implement minimum adapters** by mapping immutable business inputs into `ModelRequest`; do not duplicate validation already enforced by `GeneratedTextDraft` and `AnalysisReport`.
- [ ] **Step 4: Implement explicit provider selection**: Mock mode remains Mock; configured Qianwen uses Task 1; missing/failed Qianwen returns stable failure without fallback.
- [ ] **Step 5: Run regression** for generation facts/publication gate, analysis evidence/caching/task retry, workspace/platform isolation, API/OpenAPI/static checks and Mock fresh install.
- [ ] **Step 6: Commit** with `feat: connect qianwen text generation and analysis`, then stop before Task 3.

**Migration/OpenAPI/Security:** No migration expected. If status/error schemas change, regenerate OpenAPI/TypeScript. Usage/cost events contain counts and versions only, never text or keys. Each retry is a separately counted billed attempt and remains capped at two provider attempts.

---

### Task 3: 截图识别、视觉理解与 OCR 接入

**Files:**
- Create: `apps/api/app/modules/models/adapters/qianwen_vision.py`
- Create: `apps/api/tests/models/test_qianwen_vision.py`
- Modify: `apps/api/app/modules/models/catalog.py`
- Modify: `apps/api/app/modules/imports/ocr_adapters.py`
- Modify: `apps/api/app/modules/imports/capture_service.py`
- Modify: `apps/api/app/modules/risk_rag/scanner.py`

**Interfaces:**
- Consumes: Task 1 endpoint/error/telemetry and Task 2 provider selection.
- Produces: a Catalog entry for an exact Qwen vision snapshot and `QianwenVisionAdapter.recognize(image: bytes, mime_type: str) -> VisionRecognition`.
- Produces: OCR regions compatible with existing `RecognitionRegion` and RiskRAG scanner inputs.

- [ ] **Step 1: Recheck official vision snapshot/limits/pricing** and update ADR with an exact model ID; keep it experimental until Task 6.
- [ ] **Step 2: Write RED tests** for MIME/size/dimension limits, data URL construction or controlled temporary object URL, platform-specific metric schema, OCR confidence/coordinates, prompt injection, cross-platform fields and no image/log leakage.
- [ ] **Step 3: Run RED** and confirm no real network call.
- [ ] **Step 4: Add VISION Catalog capability** only to the reviewed vision snapshot; do not enlarge Task 1 text entry.
- [ ] **Step 5: Implement minimum adapter** using Mock Transport contracts; low-confidence fields remain empty and OCR failure preserves existing staging data.
- [ ] **Step 6: Integrate staging and risk cover OCR** without bypassing Web confirmation, workspace ownership, platform isolation or Task 4 extension-token scopes.
- [ ] **Step 7: Run regression** for imports, RiskRAG scanner, extension safe capture, OpenAPI/types, dependency audit and SBOM.
- [ ] **Step 8: Commit** with `feat: add qianwen vision and ocr adapters`, then stop before Task 4.

**Migration/OpenAPI/Security:** No raw response column. A migration is allowed only for model/recognition version metadata and must be additive. Images are billed inputs; UI/API must show that images leave the deployment and identify region/server before calls.

---

### Task 4: Embedding、版本隔离与索引重建

**Files:**
- Create: `apps/api/app/modules/models/adapters/qianwen_embedding.py`
- Create: `apps/api/tests/models/test_qianwen_embedding.py`
- Modify: `apps/api/app/modules/models/catalog.py`
- Modify: `apps/api/app/modules/risk_rag/ingestion.py`
- Modify: `apps/api/app/modules/risk_rag/retrieval.py`
- Modify: `apps/api/app/modules/exports/zip_restore.py`
- Create: `apps/api/migrations/versions/20260728_0031_qianwen_embedding_rebuild.py` if persistent rebuild metadata is required

**Interfaces:**
- Consumes: Task 1 provider configuration and safe telemetry.
- Produces: exact embedding snapshot entry with fixed `dimension` and `embedding_version`.
- Produces: `QianwenRiskEmbedder.embed_batch(texts: Sequence[str]) -> list[list[float]]`.

- [x] **Step 1: Recheck official embedding model, dimensions, batch limits, regions and pricing**; record an exact snapshot and no `latest`.
- [x] **Step 2: Write RED tests** for deterministic request batching, vector count/dimension/type, empty input, model/version/dimension mismatch, workspace/platform isolation and provider errors.
- [x] **Step 3: Run RED**, then implement strict vector parsing without padding/truncation/coercion.
- [x] **Step 4: Add versioned rebuild state** so changing model, snapshot or dimension invalidates old embeddings and retrieval never mixes versions.
- [x] **Step 5: Verify ZIP restore** queues rebuild using the target workspace’s current config and never restores vectors or source-workspace provider IDs.
- [x] **Step 6: Run RiskRAG/retrieval/restore/full regression**, migrations, OpenAPI/types, audit and SBOM.
- [x] **Step 7: Commit** with `feat: rebuild risk indexes with qianwen embeddings`, then stop before Task 5.

**Security/Cost:** Documents are untrusted data, never system messages. Batch size and total characters are capped before billed calls. Failed rebuild leaves the old complete index active until the new version commits atomically.

---

### Task 5: 封面生成、参考图和结果持久化

**Files:**
- Create: `apps/api/app/modules/models/adapters/qianwen_image.py`
- Create: `apps/api/tests/models/test_qianwen_image.py`
- Modify: `apps/api/app/modules/models/catalog.py`
- Modify: `apps/api/app/modules/generation/cover_service.py`
- Modify: `apps/api/app/modules/generation/cover_models.py`
- Modify: `apps/api/app/modules/generation/tasks.py`
- Modify: `apps/api/app/modules/generation/models.py`
- Create: `apps/api/migrations/versions/20260728_0032_qianwen_cover_artifacts.py` if current artifact/version fields are insufficient

**Interfaces:**
- Consumes: Task 1 config/error/telemetry and existing `ImageModelRequest`.
- Produces: exact image/edit model Catalog entry and `QianwenCoverImageAdapter.generate_layer(request) -> Image.Image`.
- Produces: persisted provider/model/request/version metadata plus object-storage artifact reference, never response Base64 in business columns.

- [ ] **Step 1: Recheck official image/edit endpoint, exact model IDs, reference-image support, dimensions, moderation, retention and pricing** and update ADR.
- [ ] **Step 2: Write RED tests** for four cover modes, reference purposes, signed input lifetime, size/MIME/pixel limits, output download validation, request expiry, no text rendering and provider failure cleanup.
- [ ] **Step 3: Run RED**, then add only Catalog capabilities supported by the exact image snapshot.
- [ ] **Step 4: Implement adapter and object lifecycle**; programmatic Chinese layout remains authoritative and provider output is background/subject only.
- [ ] **Step 5: Persist immutable result provenance** and prove retry/idempotency cannot duplicate billed jobs or accessible objects.
- [ ] **Step 6: Run generation/publication-gate/golden-image/full regression**, migrations, OpenAPI/types, audit and SBOM.
- [ ] **Step 7: Commit** with `feat: generate governed cover layers with qianwen`, then stop before Task 6.

**Security/Cost:** Reference images and prompts are disclosed before sending. No full provider output/logging. Failed or cancelled artifacts are inaccessible and cleaned by existing retention jobs.

---

### Task 6: 最小模型配置入口、用量控制、真实 API 受控验收与文档

**Files:**
- Create: `apps/web/src/components/models/model-config-form.tsx`
- Create: `apps/web/src/components/models/model-status.tsx`
- Create: `apps/web/src/components/models/model-config-form.test.tsx`
- Create: `apps/api/app/modules/models/usage.py`
- Create: `apps/api/tests/models/test_model_usage.py`
- Create: `tests/e2e/qianwen-config.spec.ts`
- Create: `docs/acceptance/qianwen-controlled-test-template.md`
- Modify: `apps/web/src/app/workspaces/[workspaceId]/settings/**`
- Modify: `apps/api/app/modules/models/router.py`
- Modify: `docs/architecture/0003-qianwen-provider-contract.md`
- Modify: `docs/architecture/model-adapters.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: Tasks 1–5 Catalog entries, safe configuration APIs and usage metadata.
- Produces: per-workspace call ceilings, concurrency/rate limits, usage summaries and an admin-only minimal configuration form.
- Produces: controlled real-contract evidence that can promote a specific snapshot/region/capability from experimental only when every contract case passes.

- [ ] **Step 1: Write RED API/UI tests** for admin-only configuration, generated OpenAPI types, exact Catalog choices, region/workspace validation, masked key replacement, experimental labels, data-sending/cost notice and no layout/navigation redesign.
- [ ] **Step 2: Write RED usage tests** for per-workspace concurrency, daily token/cost ceilings, 429 backoff, two-attempt billing accounting, cancellation and no content retention in usage events.
- [ ] **Step 3: Implement minimum UI and usage control**; viewer sees status only, editor cannot change credentials, and no page accepts a base URL.
- [ ] **Step 4: Run all Mock/Fake Transport gates** before any real call.
- [ ] **Step 5: Prepare controlled real test** that reads the key only from the already encrypted workspace configuration, requires an explicit admin action and budget ceiling, uses synthetic prompts/images/documents and records request IDs/token counts/latency/cost without content.
- [ ] **Step 6: Execute real tests only after explicit user confirmation**. Test Beijing and Singapore separately; never infer one region/browser/model from another. If credentials or confirmation are absent, record `not_run` and keep experimental status without blocking Mock engineering acceptance.
- [ ] **Step 7: Update ADR/docs** with exact pass/fail evidence, model lifecycle date, measured latency/cost, unverified items and rollback/disable instructions. Never claim production quality from a small sample.
- [ ] **Step 8: Run complete provider/API/Web/E2E/security/migration/audit/SBOM/fresh-install regression** and clean temporary resources.
- [ ] **Step 9: Commit** with `feat: govern qianwen configuration and controlled validation`, then stop and request direction before returning to original Task 9.

**Migration/OpenAPI/Security:** Add a migration only if durable aggregated usage/limit records are necessary; no prompt/output columns are allowed. Regenerate OpenAPI/TypeScript for every API change. Real calls require explicit budget and user confirmation; no key is accepted through chat, command arguments, `.env`, logs or test fixtures.
