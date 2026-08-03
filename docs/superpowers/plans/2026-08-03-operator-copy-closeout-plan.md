# Operator Copy Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining Easy Mode terminology and Viewer-guidance defects found by the final whole-branch review without changing product behavior or safety meaning.

**Architecture:** Extend the existing `operator-display-copy.ts` render-time mapping layer and consume it at the remaining declared workbench surfaces. Keep professional strings exact, keep server/API values authoritative, and translate only at render time. Add role-aware import guidance and final cross-surface acceptance so future pages cannot silently bypass the shared display boundary.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript 5, Tailwind CSS 4, Vitest 4, Testing Library, Playwright, pnpm 11.

## Global Constraints

- Default copy mode is `simple`; default page guidance is `on`.
- Easy mode must not expose RAG, Mock, Evidence, gate, worker, schema, vector, provider, internal state codes, raw model contracts, or internal profile IDs as primary copy.
- Professional mode preserves existing verified terminology and safe raw status values.
- High risk, risk category, low-confidence image-text recognition, missing evidence, insufficient samples, fact conflicts, model cost, destructive impact, and fixed disclaimers remain explicit in both modes.
- Viewer guidance and page-level actions may only read, understand, or tell the user to contact an Admin/Editor.
- No API contract, database model, migration, permission, business rule, dependency, online font, or third-party UI package changes.
- Switching copy or guidance must not change requests, URL, filters, form values, drafts, or workflow state.
- Existing workspace/platform isolation, secret handling, destructive confirmation order, and Task 9B `partial` status remain unchanged.
- Do not touch or commit `.superpowers/brainstorm/`.

## File Structure

### Shared display boundary

- Modify `apps/web/src/components/workbench/operator-display-copy.ts`
  - Add controlled risk-category aliases and reusable Easy/Professional descriptions for knowledge governance, export exclusions, background-task metadata, and generation/model summaries.
- Create `apps/web/src/components/workbench/operator-display-copy.test.ts`
  - Prove known and unknown risk categories preserve meaning and that every new mapping retains exact professional text.

### Remaining declared surfaces

- Modify and test:
  - `apps/web/src/components/risk/risk-knowledge-center.tsx`
  - `apps/web/src/components/risk/risk-knowledge-center.test.tsx`
  - `apps/web/src/components/exports/export-backup-center.tsx`
  - `apps/web/src/components/exports/export-backup-center.test.tsx`
  - `apps/web/src/components/workbench/generation-wizard.tsx`
  - `apps/web/src/components/workbench/generation-wizard.test.tsx`
  - `apps/web/src/components/exports/trash-center.tsx`
  - `apps/web/src/components/exports/trash-center.test.tsx`
  - `apps/web/src/components/charts/account-dashboard.tsx`
  - `apps/web/src/components/charts/charts.test.tsx`
  - `apps/web/src/components/content/content-detail-tabs.tsx`
  - `apps/web/src/components/content/content-detail-tabs.test.tsx`

### Viewer and final acceptance

- Modify:
  - `apps/web/src/components/imports/import-center.test.tsx`
  - `apps/web/src/components/workbench/operator-display-copy.ts`
  - `tests/e2e/workbench-guidance.spec.ts`
  - `tests/e2e/workbench-visual.spec.ts`
  - `docs/acceptance/requirements-traceability.md`

---

### Task 1: Complete Easy/Professional Copy on Remaining Declared Surfaces

**Files:**
- Create: `apps/web/src/components/workbench/operator-display-copy.test.ts`
- Modify: `apps/web/src/components/workbench/operator-display-copy.ts`
- Modify/Test: the six surface/component pairs listed under “Remaining declared surfaces”.

**Interfaces:**
- Consumes: `displayCopy`, `displayText`, `CopyMode`, `useOptionalExperiencePreferences`.
- Produces:
  - `riskTypeCopy(value: string): ModeAwareCopy`
  - `knowledgeTermCopy(value: "chunk" | "citation" | "bundle" | "mock" | "rag" | "ocr"): ModeAwareCopy`
  - `exportBoundaryCopy(value: "prompt" | "embedding" | "provider_workspace" | "worker_runtime"): ModeAwareCopy`
  - `generationTermCopy(value: "provider" | "gate" | "ocr" | "experimental"): ModeAwareCopy`
  - `internalReferenceCopy(value: string | null | undefined, easyLabel: string): ModeAwareCopy`

- [x] **Step 1: Write failing shared-mapping tests**

Add tests that assert:

```ts
expect(riskTypeCopy("contact_format")).toEqual({
  simple: "联系方式格式风险",
  professional: "contact_format",
});
expect(riskTypeCopy("effect_claim")).toEqual({
  simple: "功效宣传风险",
  professional: "effect_claim",
});
expect(riskTypeCopy("unknown_rule_id")).toEqual({
  simple: "其他风险类型，具体原因见下方说明",
  professional: "unknown_rule_id",
});
expect(knowledgeTermCopy("bundle")).toEqual({
  simple: "本次判断资料",
  professional: "Evidence Bundle",
});
expect(exportBoundaryCopy("worker_runtime")).toEqual({
  simple: "后台任务运行状态",
  professional: "Worker claim、lease 和 heartbeat",
});
expect(generationTermCopy("experimental")).toEqual({
  simple: "试用状态，真实效果和费用尚未完成验收",
  professional: "Provider experimental",
});
```

The controlled risk aliases must include at least:

```ts
{
  contact_format: "联系方式格式风险",
  external_contact: "站外联系方式风险",
  absolute_claim: "绝对化宣传风险",
  unverified_claim: "未经确认的宣传风险",
  price_claim: "价格信息风险",
  effect_claim: "功效宣传风险",
  certification_claim: "认证资质风险",
  material_claim: "材质描述风险",
}
```

- [x] **Step 2: Verify RED**

Run:

```bash
pnpm --filter web exec vitest run src/components/workbench/operator-display-copy.test.ts
```

Expected: FAIL because the new functions and category-preserving aliases do not exist and the current unknown/category output is generic.

- [x] **Step 3: Write failing populated-surface tests**

For every listed surface, render both modes with populated data and assert:

```ts
expect(easy.container.textContent).not.toMatch(
  /\b(?:Chunk|Citation|Evidence Bundle|Mock|RAG|OCR|Embedding|Provider|Prompt|Worker|lease|heartbeat|INSUFFICIENT_SAMPLE)\b/,
);
```

Also assert Easy Mode does not expose:

- raw internal profile IDs;
- raw model contract/configuration versions;
- raw risk type IDs or raw task states;
- “门禁” or “向量” as a primary label.

Then assert the relevant Easy Mode replacements and exact professional strings. Required surface expectations:

- Risk knowledge: `规则片段`, `引用检查`, `本次判断资料`, `固定合成评估`, `样本不足`, `图片文字识别`.
- Export/backup: `生成指令`, `资料检索索引`, `模型服务私有标识`, `后台任务运行状态`.
- Generation: `模型服务`, `检查规则`, `图片文字识别`, and the exact experimental warning.
- Trash: `关联资料决定` instead of `Evidence 决定`.
- Dashboard: `服务端展示条件` instead of `候选或异常门禁`.
- Content overview: `发布时目标配置：已记录，可在专业模式查看` and the same for the benchmark, without IDs.

For risk findings, assert the severity, mapped category, reason, region, and required human review remain visible.

- [x] **Step 4: Verify surface RED**

Run the exact six focused test files:

```bash
pnpm --filter web exec vitest run \
  src/components/risk/risk-knowledge-center.test.tsx \
  src/components/exports/export-backup-center.test.tsx \
  src/components/workbench/generation-wizard.test.tsx \
  src/components/exports/trash-center.test.tsx \
  src/components/charts/charts.test.tsx \
  src/components/content/content-detail-tabs.test.tsx
```

Expected: FAIL on the professional terms and raw identifiers confirmed by the final review.

- [x] **Step 5: Implement the shared mappings**

Implement controlled `ModeAwareCopy` functions in `operator-display-copy.ts`. Unknown risk types must not reveal the raw ID in Easy Mode, but must say that the type is outside the controlled alias list and direct the user to the visible reason. Professional Mode returns the exact input.

Do not add new business classification, change API values, or infer platform safety.

- [x] **Step 6: Migrate each remaining surface**

Read `copyMode` from the existing preference context and render all cited labels/values through `displayText(...)`. Keep fixed warnings unchanged in meaning. Do not hide advanced data; Easy Mode may say “已记录，可在专业模式查看” where the raw identifier has no safe operator translation.

- [x] **Step 7: Verify GREEN and full Web regression**

Run:

```bash
pnpm --filter web exec vitest run \
  src/components/workbench/operator-display-copy.test.ts \
  src/components/risk/risk-knowledge-center.test.tsx \
  src/components/exports/export-backup-center.test.tsx \
  src/components/workbench/generation-wizard.test.tsx \
  src/components/exports/trash-center.test.tsx \
  src/components/charts/charts.test.tsx \
  src/components/content/content-detail-tabs.test.tsx
pnpm --filter web test:run
pnpm --filter web lint
pnpm --filter web typecheck
pnpm --filter web build
```

Expected: all PASS with exact professional terminology preserved.

- [x] **Step 8: Commit**

```bash
git add apps/web/src/components
git commit -m "fix(web): complete easy-mode surface copy"
```

---

### Task 2: Close Viewer Guidance and Final Acceptance

**Files:**
- Modify: `apps/web/src/components/workbench/operator-display-copy.ts`
- Modify: `apps/web/src/components/workbench/operator-display-copy.test.ts`
- Modify: `apps/web/src/components/imports/import-center.test.tsx`
- Modify: `tests/e2e/workbench-guidance.spec.ts`
- Modify: `tests/e2e/workbench-visual.spec.ts`
- Modify: `tests/e2e/workbench-visual.spec.ts-snapshots/*` only when deterministic content legitimately changes
- Modify: `docs/acceptance/requirements-traceability.md`

**Interfaces:**
- Consumes: `importHistoryActionCopy(value, role)`.
- Produces: professional Viewer copy that is still read/contact-only.

- [x] **Step 1: Write the failing Viewer tests**

Add exact assertions:

```ts
expect(importHistoryActionCopy("review", "viewer")).toEqual({
  simple: "查看等待确认的导入记录；需要确认时请联系管理员或编辑者。",
  professional: "Viewer 只读查看等待确认的导入记录；继续确认需要 Admin 或 Editor。",
});
```

Render `ImportCenter` as Viewer in Professional Mode and assert:

```ts
expect(screen.getByText(
  "Viewer 只读查看等待确认的导入记录；继续确认需要 Admin 或 Editor。",
)).toBeVisible();
expect(screen.queryByText("Viewer 只读继续确认")).not.toBeInTheDocument();
```

- [x] **Step 2: Verify RED**

Run:

```bash
pnpm --filter web exec vitest run \
  src/components/workbench/operator-display-copy.test.ts \
  src/components/imports/import-center.test.tsx
```

Expected: FAIL because current Professional Viewer copy says `Viewer 只读继续确认`.

- [x] **Step 3: Implement the minimal role-safe mapping**

For Viewer:

- `review` uses the exact read/contact strings above.
- `retry` says the Viewer may read the failure and must contact Admin/Editor to retry.
- `wait` and `open_result` remain read-only viewing actions.

Admin/Editor strings remain unchanged.

- [x] **Step 4: Verify focused GREEN**

Run the Step 2 command again. Expected: PASS.

- [x] **Step 5: Strengthen E2E and visual acceptance**

Extend the existing guidance E2E to visit imports in Professional Mode as Viewer and assert the exact read/contact copy and absence of `Viewer 只读继续确认`.

Update the visual fixture only if the controlled test data contains a reviewable import record. If it does not, do not fabricate one solely for a screenshot; record unit/E2E evidence instead.

- [x] **Step 6: Run final verification**

Run:

```bash
pnpm --filter web test:run
pnpm --filter web lint
pnpm --filter web typecheck
pnpm --filter web build
pnpm schemas:check
pnpm metrics:check
pnpm secret:scan
git diff --check
pnpm --dir tests/e2e exec playwright test \
  workbench-guidance.spec.ts \
  workbench-navigation.spec.ts \
  workbench-mobile.spec.ts
pnpm --dir tests/e2e exec playwright test \
  workbench-visual.spec.ts --update-snapshots --timeout=120000
pnpm --dir tests/e2e exec playwright test \
  workbench-visual.spec.ts --timeout=120000
bash scripts/verify-fresh-install.sh
```

Expected:

- Web unit/component tests all PASS.
- Guidance/navigation/mobile E2E all PASS.
- Visual update and no-update rerun both PASS.
- Fresh install and restart both PASS, then all isolated resources are removed.
- No API/schema/metric/secret drift.
- `UX-COPY-01` remains `partial` with `independent_non_developer_pending`; do not claim Task 9B passed.

- [x] **Step 7: Review the declared-surface leak scan**

Run:

```bash
rg -n \
  'Chunk|Citation|Evidence Bundle|Mock|INSUFFICIENT_SAMPLE|RAG|OCR|Embedding|Provider|Prompt|Worker|lease|heartbeat|门禁|向量' \
  apps/web/src/components
```

Every remaining match must be one of:

- professional branch text;
- fixed security disclaimer that accurately names excluded secret/internal data;
- test fixture/assertion;
- a component outside the approved workbench scope.

Document each allowed category in the task report. Any unconditional primary Easy Mode match is a failure.

- [x] **Step 8: Commit**

```bash
git add \
  apps/web/src/components/workbench/operator-display-copy.ts \
  apps/web/src/components/workbench/operator-display-copy.test.ts \
  apps/web/src/components/imports/import-center.test.tsx \
  tests/e2e/workbench-guidance.spec.ts \
  tests/e2e/workbench-visual.spec.ts \
  tests/e2e/workbench-visual.spec.ts-snapshots \
  docs/acceptance/requirements-traceability.md
git commit -m "test: close operator copy acceptance"
```
