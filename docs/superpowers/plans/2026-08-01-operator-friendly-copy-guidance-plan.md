# Operator-Friendly Copy and Guidance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add member-scoped easy/professional copy modes and persistent page guidance so operations users can understand every formal workbench module without learning developer terminology.

**Architecture:** Keep all business data and decisions authoritative in the existing APIs. Add a browser-only experience preference provider inside `WorkspaceShell`, a centralized page copy/guidance catalog, and reusable guided header/state presentation components; then migrate the 16 formal modules and key detail pages in reviewable groups. No mode switch may change requests, permissions, saved content, generation prompts, filters, or workflow state.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript 5, Tailwind CSS 4, Vitest 4, Testing Library, Playwright, pnpm 11.

## Global Constraints

- Default copy mode is `simple`; default page guidance is `on`.
- The two preferences are independent and stored per member under `operations-ai:copy-mode:{memberId}` and `operations-ai:page-guidance:{memberId}`.
- Even when guidance is off, every covered page retains one plain-language purpose sentence below its title.
- Easy mode speaks in operations outcomes and next actions; professional mode preserves the existing verified terminology.
- Do not expose RAG, Mock, Evidence, gate, worker, schema, vector, provider, or internal state-code terminology as the primary easy-mode copy.
- High risk, low-confidence OCR, missing evidence, insufficient samples, fact conflicts, real-model cost, destructive impact, and fixed disclaimers remain explicit in both modes.
- Admin, Editor, and Viewer guidance must never suggest an action the role cannot perform.
- Demo preferences and private-member preferences must not share a storage key.
- No API contract, database model, migration, permission, business rule, dependency, online font, or third-party UI package changes.
- The experience controls must be keyboard accessible, screen-reader labelled, and usable at 390px.
- The full scope is the 16 formal modules plus content, account, style, member, and model detail surfaces named in the approved spec.

---

## File Structure

### New files

- `apps/web/src/components/workbench/experience-preferences.ts`
  - Pure storage keys, validation, defaults, and safe read/write/clear functions.
- `apps/web/src/components/workbench/experience-preferences-context.tsx`
  - React provider and hook for the current member’s two display preferences.
- `apps/web/src/components/workbench/experience-controls.tsx`
  - Desktop/mobile accessible controls for copy mode and guidance.
- `apps/web/src/components/workbench/operator-copy-catalog.ts`
  - Stable page IDs and simple/professional purpose copy.
- `apps/web/src/components/workbench/page-guidance-catalog.ts`
  - Role-aware next actions, steps, concepts, and common blockers.
- `apps/web/src/components/workbench/page-guide.tsx`
  - Compact always-visible purpose plus optional expandable guidance.
- `apps/web/src/components/workbench/guided-page-header.tsx`
  - Composition of the existing `PageHeader` and `PageGuide`.
- `apps/web/src/components/workbench/experience-preferences.test.ts`
  - Storage boundary tests.
- `apps/web/src/components/workbench/operator-copy-catalog.test.ts`
  - Completeness, terminology, role, and risk-copy tests.
- `apps/web/src/components/workbench/page-guide.test.tsx`
  - Rendering and accessibility tests.
- `tests/e2e/workbench-guidance.spec.ts`
  - Role, persistence, mobile, and no-business-state-change acceptance.

### Existing files changed by foundation tasks

- `apps/web/src/components/workbench/workspace-shell.tsx`
  - Mount the experience provider and clear only its namespace on an expired session.
- `apps/web/src/components/workbench/workspace-topbar.tsx`
  - Render the shared experience controls.
- `apps/web/src/components/workbench/ui.tsx`
  - Add mode-aware copy support to shared state components without changing existing string callers.
- `apps/web/src/components/workbench/ui.test.tsx`
  - Preserve existing semantics and verify easy/professional text switching.
- `apps/web/src/components/workbench/workspace-shell.test.tsx`
  - Verify topbar controls, member isolation, mobile access, and expiry cleanup.

### Existing files changed by page migration tasks

- Overview and operations:
  - `apps/web/src/components/workbench/workbench-overview.tsx`
  - `apps/web/src/components/account/account-list.tsx`
  - `apps/web/src/components/charts/account-dashboard.tsx`
  - `apps/web/src/components/account/columns-center.tsx`
  - `apps/web/src/components/content/content-list.tsx`
  - `apps/web/src/components/content/content-detail-tabs.tsx`
  - `apps/web/src/components/imports/import-center.tsx`
  - `apps/web/src/components/analysis/analysis-queue.tsx`
- Creation and assets:
  - `apps/web/src/components/workbench/generation-wizard.tsx`
  - `apps/web/src/components/risk/preflight-queue.tsx`
  - `apps/web/src/components/viral/viral-library.tsx`
  - `apps/web/src/components/styles/style-account-selector.tsx`
  - `apps/web/src/components/styles/style-profile-center.tsx`
  - `apps/web/src/components/facts/fact-source-center.tsx`
- Management and settings:
  - `apps/web/src/components/exports/export-backup-center.tsx`
  - `apps/web/src/components/operations/job-operations.tsx`
  - `apps/web/src/components/risk/risk-knowledge-center.tsx`
  - `apps/web/src/components/exports/trash-center.tsx`
  - `apps/web/src/components/workspace/workspace-settings.tsx`
  - `apps/web/src/components/workspace/member-settings.tsx`
  - `apps/web/src/components/models/model-config-form.tsx`

### Acceptance files

- `tests/e2e/workbench-visual.spec.ts`
  - Add deterministic easy/professional/guidance-off/mobile baselines.
- `docs/acceptance/requirements-traceability.md`
  - Record the new automated and independent-user acceptance evidence.
- `docs/acceptance/non-developer-participant-task-card.md`
  - Replace developer wording with the exact operator tasks used for Task 9B.

---

### Task 1: Member-Scoped Experience Preferences and Topbar Controls

**Files:**
- Create: `apps/web/src/components/workbench/experience-preferences.ts`
- Create: `apps/web/src/components/workbench/experience-preferences-context.tsx`
- Create: `apps/web/src/components/workbench/experience-controls.tsx`
- Create: `apps/web/src/components/workbench/experience-preferences.test.ts`
- Modify: `apps/web/src/components/workbench/workspace-shell.tsx`
- Modify: `apps/web/src/components/workbench/workspace-topbar.tsx`
- Modify: `apps/web/src/components/workbench/workspace-shell.test.tsx`
- Modify: `apps/web/src/components/demo-workspace.tsx`
- Modify: `apps/web/src/components/demo-workspace.test.tsx`

**Interfaces:**
- Produces:
  - `type CopyMode = "simple" | "professional"`
  - `type PageGuidancePreference = "on" | "off"`
  - `type ExperiencePreferences = { copyMode: CopyMode; pageGuidance: PageGuidancePreference }`
  - `readExperiencePreferences(storage, memberId): ExperiencePreferences`
  - `writeCopyMode(storage, memberId, mode): void`
  - `writePageGuidance(storage, memberId, preference): void`
  - `clearExperiencePreferences(storage): void`
  - `ExperiencePreferencesProvider`
  - `useExperiencePreferences(): ExperiencePreferenceContextValue`
  - `useOptionalExperiencePreferences(): ExperiencePreferenceContextValue | null`
  - `ExperienceControls`
- Consumes: current `WorkbenchContext.member_id`, `WorkspaceTopbar`, and session-expiry handling.

- [ ] **Step 1: Write failing pure preference tests**

Create `experience-preferences.test.ts` with exact boundaries:

```ts
import { beforeEach, expect, test } from "vitest";
import {
  clearExperiencePreferences,
  readExperiencePreferences,
  writeCopyMode,
  writePageGuidance,
} from "./experience-preferences";

beforeEach(() => localStorage.clear());

test("defaults to simple copy with guidance on", () => {
  expect(readExperiencePreferences(localStorage, "member-1")).toEqual({
    copyMode: "simple",
    pageGuidance: "on",
  });
});

test("stores the two preferences independently per member", () => {
  writeCopyMode(localStorage, "member-1", "professional");
  writePageGuidance(localStorage, "member-1", "off");
  writeCopyMode(localStorage, "member-2", "simple");

  expect(readExperiencePreferences(localStorage, "member-1")).toEqual({
    copyMode: "professional",
    pageGuidance: "off",
  });
  expect(readExperiencePreferences(localStorage, "member-2")).toEqual({
    copyMode: "simple",
    pageGuidance: "on",
  });
});

test("rejects invalid stored values without copying them to another member", () => {
  localStorage.setItem("operations-ai:copy-mode:member-1", "PRIVATE_DATA");
  localStorage.setItem("operations-ai:page-guidance:member-1", "sometimes");
  expect(readExperiencePreferences(localStorage, "member-1")).toEqual({
    copyMode: "simple",
    pageGuidance: "on",
  });
});

test("clears only experience preference keys", () => {
  localStorage.setItem("operations-ai:copy-mode:member-1", "professional");
  localStorage.setItem("operations-ai:page-guidance:member-1", "off");
  localStorage.setItem("operations-ai:sidebar:member-1", "collapsed");
  localStorage.setItem("unrelated", "keep");
  clearExperiencePreferences(localStorage);
  expect(localStorage.getItem("operations-ai:copy-mode:member-1")).toBeNull();
  expect(localStorage.getItem("operations-ai:page-guidance:member-1")).toBeNull();
  expect(localStorage.getItem("operations-ai:sidebar:member-1")).toBe("collapsed");
  expect(localStorage.getItem("unrelated")).toBe("keep");
});
```

- [ ] **Step 2: Run the pure tests and verify RED**

Run:

```bash
pnpm --filter web test:run -- src/components/workbench/experience-preferences.test.ts
```

Expected: FAIL because `experience-preferences.ts` does not exist.

- [ ] **Step 3: Implement safe storage functions**

Create `experience-preferences.ts`:

```ts
export type CopyMode = "simple" | "professional";
export type PageGuidancePreference = "on" | "off";
export type ExperiencePreferences = {
  copyMode: CopyMode;
  pageGuidance: PageGuidancePreference;
};

export const DEFAULT_EXPERIENCE_PREFERENCES: ExperiencePreferences = {
  copyMode: "simple",
  pageGuidance: "on",
};

const copyModeKey = (memberId: string) =>
  `operations-ai:copy-mode:${memberId}`;
const guidanceKey = (memberId: string) =>
  `operations-ai:page-guidance:${memberId}`;

export function readExperiencePreferences(
  storage: Pick<Storage, "getItem">,
  memberId: string,
): ExperiencePreferences {
  try {
    const copyMode = storage.getItem(copyModeKey(memberId));
    const pageGuidance = storage.getItem(guidanceKey(memberId));
    return {
      copyMode: copyMode === "professional" ? "professional" : "simple",
      pageGuidance: pageGuidance === "off" ? "off" : "on",
    };
  } catch {
    return DEFAULT_EXPERIENCE_PREFERENCES;
  }
}

export function writeCopyMode(
  storage: Pick<Storage, "setItem">,
  memberId: string,
  mode: CopyMode,
): void {
  try {
    storage.setItem(copyModeKey(memberId), mode);
  } catch {
    // Display preferences are optional; business workflows continue.
  }
}

export function writePageGuidance(
  storage: Pick<Storage, "setItem">,
  memberId: string,
  preference: PageGuidancePreference,
): void {
  try {
    storage.setItem(guidanceKey(memberId), preference);
  } catch {
    // Display preferences are optional; business workflows continue.
  }
}

export function clearExperiencePreferences(
  storage: Pick<Storage, "key" | "length" | "removeItem">,
): void {
  const keys: string[] = [];
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (
      key?.startsWith("operations-ai:copy-mode:")
      || key?.startsWith("operations-ai:page-guidance:")
    ) {
      keys.push(key);
    }
  }
  for (const key of keys) storage.removeItem(key);
}
```

- [ ] **Step 4: Run the pure tests and verify GREEN**

Run the Step 2 command.

Expected: 4 tests PASS.

- [ ] **Step 5: Write failing provider/topbar tests**

Extend `workspace-shell.test.tsx`:

```tsx
test("offers independent easy/professional and guidance controls", async () => {
  const user = userEvent.setup();
  render(<WorkspaceShell context={context}><p>页面业务内容</p></WorkspaceShell>);

  expect(screen.getByRole("radiogroup", { name: "文案模式" })).toBeVisible();
  expect(screen.getByRole("radio", { name: "易懂" })).toBeChecked();
  expect(screen.getByRole("switch", { name: "页面引导" })).toBeChecked();

  await user.click(screen.getByRole("radio", { name: "专业" }));
  expect(screen.getByRole("switch", { name: "页面引导" })).toBeChecked();
  expect(localStorage.getItem(
    "operations-ai:copy-mode:member-admin",
  )).toBe("professional");

  await user.click(screen.getByRole("switch", { name: "页面引导" }));
  expect(screen.getByRole("radio", { name: "专业" })).toBeChecked();
  expect(localStorage.getItem(
    "operations-ai:page-guidance:member-admin",
  )).toBe("off");
});

test("keeps preferences isolated when the current member changes", () => {
  localStorage.setItem(
    "operations-ai:copy-mode:member-admin",
    "professional",
  );
  const { rerender } = render(
    <WorkspaceShell context={context}><p>管理员页面</p></WorkspaceShell>,
  );
  expect(screen.getByRole("radio", { name: "专业" })).toBeChecked();

  rerender(
    <WorkspaceShell
      context={{
        ...context,
        member_id: "member-viewer",
        member_display_name: "运营查看者",
        role: "viewer",
      }}
    >
      <p>查看者页面</p>
    </WorkspaceShell>,
  );
  expect(screen.getByRole("radio", { name: "易懂" })).toBeChecked();
});
```

Also extend the existing 401 cleanup test so it seeds both new namespaces and asserts they are cleared while `unrelated-preference` remains.

- [ ] **Step 6: Run shell tests and verify RED**

Run:

```bash
pnpm --filter web test:run -- src/components/workbench/workspace-shell.test.tsx
```

Expected: FAIL because no provider or controls exist.

- [ ] **Step 7: Implement the provider and controls**

Create `experience-preferences-context.tsx` with this public shape:

```tsx
"use client";

import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useSyncExternalStore,
} from "react";
import {
  readExperiencePreferences,
  writeCopyMode,
  writePageGuidance,
  type CopyMode,
  type ExperiencePreferences,
  type PageGuidancePreference,
} from "./experience-preferences";

export type ExperiencePreferenceContextValue = ExperiencePreferences & {
  setCopyMode: (mode: CopyMode) => void;
  setPageGuidance: (preference: PageGuidancePreference) => void;
};

const ExperiencePreferenceContext =
  createContext<ExperiencePreferenceContextValue | null>(null);

export function ExperiencePreferencesProvider({
  memberId,
  children,
}: {
  memberId: string;
  children: ReactNode;
}) {
  const eventName = `operations-ai:experience-change:${memberId}`;
  const subscribe = useCallback((notify: () => void) => {
    const onStorage = (event: StorageEvent) => {
      if (event.key?.endsWith(`:${memberId}`)) notify();
    };
    window.addEventListener("storage", onStorage);
    window.addEventListener(eventName, notify);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(eventName, notify);
    };
  }, [eventName, memberId]);
  const snapshot = useCallback(() => {
    const value = readExperiencePreferences(window.localStorage, memberId);
    return `${value.copyMode}|${value.pageGuidance}`;
  }, [memberId]);
  const serialized = useSyncExternalStore(
    subscribe,
    snapshot,
    () => "simple|on",
  );
  const [copyMode, pageGuidance] = serialized.split("|") as [
    CopyMode,
    PageGuidancePreference,
  ];
  const preferences = { copyMode, pageGuidance };
  const notify = () => window.dispatchEvent(new Event(eventName));
  return (
    <ExperiencePreferenceContext.Provider value={{
      ...preferences,
      setCopyMode: (mode) => {
        writeCopyMode(window.localStorage, memberId, mode);
        notify();
      },
      setPageGuidance: (preference) => {
        writePageGuidance(window.localStorage, memberId, preference);
        notify();
      },
    }}>
      {children}
    </ExperiencePreferenceContext.Provider>
  );
}

export function useExperiencePreferences(): ExperiencePreferenceContextValue {
  const value = useContext(ExperiencePreferenceContext);
  if (!value) {
    throw new Error("useExperiencePreferences requires ExperiencePreferencesProvider");
  }
  return value;
}

export function useOptionalExperiencePreferences():
  ExperiencePreferenceContextValue | null {
  return useContext(ExperiencePreferenceContext);
}
```

Create `experience-controls.tsx`:

```tsx
"use client";

import { useExperiencePreferences } from "./experience-preferences-context";

function ControlFields() {
  const {
    copyMode,
    pageGuidance,
    setCopyMode,
    setPageGuidance,
  } = useExperiencePreferences();
  return (
    <div className="flex flex-wrap items-center gap-2" aria-label="界面说明设置">
      <div
        aria-label="文案模式"
        className="inline-flex rounded-lg border bg-white p-1"
        role="radiogroup"
      >
        {([
          ["simple", "易懂"],
          ["professional", "专业"],
        ] as const).map(([value, label]) => (
          <button
            aria-checked={copyMode === value}
            className={copyMode === value
              ? "rounded-md bg-[var(--brand)] px-2.5 py-1.5 text-sm font-semibold text-white"
              : "rounded-md px-2.5 py-1.5 text-sm text-[var(--text-secondary)]"}
            key={value}
            onClick={() => setCopyMode(value)}
            role="radio"
            type="button"
          >
            {label}
          </button>
        ))}
      </div>
      <button
        aria-checked={pageGuidance === "on"}
        aria-label="页面引导"
        className="rounded-lg border bg-white px-3 py-2 text-sm"
        onClick={() => setPageGuidance(pageGuidance === "on" ? "off" : "on")}
        role="switch"
        type="button"
      >
        引导：{pageGuidance === "on" ? "开" : "关"}
      </button>
    </div>
  );
}

export function ExperienceControls({ compact = false }: { compact?: boolean }) {
  if (!compact) return <ControlFields />;
  return (
    <details className="relative">
      <summary className="cursor-pointer rounded-lg border bg-white px-3 py-2 text-sm">
        界面说明
      </summary>
      <div className="absolute right-0 z-50 mt-2 w-64 rounded-xl border bg-white p-3 shadow-lg">
        <ControlFields />
      </div>
    </details>
  );
}
```

Mount `ExperiencePreferencesProvider` inside `WorkspaceShell` around both the topbar and page content. Render `<ExperienceControls compact={isMobile} />` in `WorkspaceTopbar` before the Help link. On a 401, call both `clearNavigationPreferences` and `clearExperiencePreferences`.

Wrap the public Demo’s existing `<main>` return in `ExperiencePreferencesProvider` and replace the single header link with this exact action group:

```tsx
<ExperiencePreferencesProvider memberId="demo-public">
  <main className="min-h-screen bg-[var(--canvas)] px-4 py-8 text-[var(--text-primary)] sm:px-6">
    {/* Keep the current DemoBanner, heading, cards, and Mock generation panel. */}
    <div className="flex flex-wrap items-center gap-2">
      <ExperienceControls />
      <Link
        className="rounded-lg bg-[var(--brand)] px-4 py-2 text-center text-sm font-semibold text-white"
        href="/enter"
      >
        进入私有工作区
      </Link>
    </div>
  </main>
</ExperiencePreferencesProvider>
```

The comment means the current children remain byte-for-byte except that the existing header link moves into the shown action group; do not create a placeholder component. The fixed key `demo-public` is never constructed from or reused by a private `member_id`. Add a Demo test that seeds `operations-ai:copy-mode:member-admin=professional`, renders Demo, and asserts Demo still defaults to Easy.

- [ ] **Step 8: Verify task behavior**

Run:

```bash
pnpm --filter web test:run -- \
  src/components/workbench/experience-preferences.test.ts \
  src/components/workbench/workspace-shell.test.tsx
pnpm --filter web lint
pnpm --filter web typecheck
```

Expected: all tests PASS; lint and typecheck exit 0.

- [ ] **Step 9: Commit**

```bash
git add \
  apps/web/src/components/workbench/experience-preferences.ts \
  apps/web/src/components/workbench/experience-preferences-context.tsx \
  apps/web/src/components/workbench/experience-controls.tsx \
  apps/web/src/components/workbench/experience-preferences.test.ts \
  apps/web/src/components/workbench/workspace-shell.tsx \
  apps/web/src/components/workbench/workspace-topbar.tsx \
  apps/web/src/components/workbench/workspace-shell.test.tsx \
  apps/web/src/components/demo-workspace.tsx \
  apps/web/src/components/demo-workspace.test.tsx
git commit -m "feat: add member-scoped workbench guidance preferences"
```

---

### Task 2: Complete Operator Copy and Role-Aware Guidance Catalogs

**Files:**
- Create: `apps/web/src/components/workbench/operator-copy-catalog.ts`
- Create: `apps/web/src/components/workbench/page-guidance-catalog.ts`
- Create: `apps/web/src/components/workbench/operator-copy-catalog.test.ts`

**Interfaces:**
- Consumes: `CopyMode` from Task 1 and `WorkbenchRole` from `navigation.ts`.
- Produces:
  - `type OperatorPageId`
  - `type ModeAwareCopy = { simple: string; professional: string }`
  - `OPERATOR_COPY_CATALOG: Record<OperatorPageId, OperatorPageCopy>`
  - `PAGE_GUIDANCE_CATALOG: Record<OperatorPageId, PageGuidanceEntry>`
  - `copyForMode(copy, mode): string`
  - `nextActionForRole(entry, role): GuidanceAction`

- [ ] **Step 1: Write failing catalog contract tests**

Create `operator-copy-catalog.test.ts`:

```ts
import { expect, test } from "vitest";
import { ALL_WORKBENCH_MODULE_LABELS } from "./navigation";
import {
  OPERATOR_COPY_CATALOG,
  OPERATOR_PAGE_IDS,
  copyForMode,
} from "./operator-copy-catalog";
import {
  PAGE_GUIDANCE_CATALOG,
  nextActionForRole,
} from "./page-guidance-catalog";

test("covers all 16 formal modules and approved detail surfaces", () => {
  expect(OPERATOR_PAGE_IDS).toEqual([
    "overview", "contents", "contentDetail", "imports", "analysis",
    "accounts", "accountDashboard", "columns", "generation", "preflight",
    "viralLibrary", "styles", "styleProfile", "facts", "exports", "jobs",
    "riskKnowledge", "trash", "settings", "settingsMembers",
    "settingsModels",
  ]);
  expect(new Set(ALL_WORKBENCH_MODULE_LABELS)).toHaveLength(16);
  for (const id of OPERATOR_PAGE_IDS) {
    expect(OPERATOR_COPY_CATALOG[id].purpose.simple.length).toBeGreaterThan(12);
    expect(OPERATOR_COPY_CATALOG[id].purpose.professional.length).toBeGreaterThan(12);
    expect(PAGE_GUIDANCE_CATALOG[id].steps.length).toBeGreaterThanOrEqual(3);
  }
});

test("keeps developer terms out of primary easy copy", () => {
  const forbidden = /\b(?:RAG|Mock|Evidence|Worker|Schema|Provider|API)\b|门禁|向量|幂等/i;
  for (const page of Object.values(OPERATOR_COPY_CATALOG)) {
    expect(page.purpose.simple).not.toMatch(forbidden);
  }
});

test("preserves exact professional copy while selecting simple by default", () => {
  const copy = OPERATOR_COPY_CATALOG.analysis.purpose;
  expect(copyForMode(copy, "simple")).toBe(
    "找出还没分析或分析失败的作品，并查看问题和改进建议。",
  );
  expect(copyForMode(copy, "professional")).toBe(
    "队列只展示服务端已经确认的分析状态、样本、Evidence 和置信度；不同平台分别筛选。",
  );
});

test("never gives a viewer a write action", () => {
  for (const entry of Object.values(PAGE_GUIDANCE_CATALOG)) {
    const action = nextActionForRole(entry, "viewer");
    expect(action.kind).not.toBe("write");
  }
});

test("keeps required safety meaning in both modes", () => {
  const risk = OPERATOR_COPY_CATALOG.preflight.safety;
  expect(risk.simple).toMatch(/不代表安全|人工检查|不能发布/);
  expect(risk.professional).toMatch(/RAG|OCR|证据|门禁/);
});
```

- [ ] **Step 2: Run catalog tests and verify RED**

Run:

```bash
pnpm --filter web test:run -- src/components/workbench/operator-copy-catalog.test.ts
```

Expected: FAIL because both catalogs do not exist.

- [ ] **Step 3: Define exact page IDs and copy contracts**

Create `operator-copy-catalog.ts` with:

```ts
import type { CopyMode } from "./experience-preferences";

export const OPERATOR_PAGE_IDS = [
  "overview", "contents", "contentDetail", "imports", "analysis",
  "accounts", "accountDashboard", "columns", "generation", "preflight",
  "viralLibrary", "styles", "styleProfile", "facts", "exports", "jobs",
  "riskKnowledge", "trash", "settings", "settingsMembers",
  "settingsModels",
] as const;

export type OperatorPageId = (typeof OPERATOR_PAGE_IDS)[number];
export type ModeAwareCopy = {
  simple: string;
  professional: string;
};
export type OperatorPageCopy = {
  title: string;
  purpose: ModeAwareCopy;
  safety?: ModeAwareCopy;
};
export const copyForMode = (
  copy: ModeAwareCopy,
  mode: CopyMode,
): string => copy[mode];
```

Add the following exact catalog content:

| ID | Title | Easy purpose | Professional purpose |
| --- | --- | --- | --- |
| overview | 工作台总览 | 看清各账号目前缺什么数据、有哪些待处理内容，以及现在最值得先做哪一件事。 | 按账号分别查看数据完整度、风险和下一步，不混算不同平台的业务指标。 |
| contents | 内容库 | 集中查看每条作品、发布状态、数据、分析和风险结果。 | 按平台、账号、栏目和数据状态查找内容；平台数据始终分别展示。 |
| contentDetail | 内容详情 | 在一处查看这条作品的数据、分析、风险和生成记录。 | 展示服务端可确认的生命周期、同口径快照、分析版本、风险扫描和安全关联生成记录。 |
| imports | 数据导入 | 把作品和发布后的运营数据录入系统；确认前不会写入正式记录。 | 四种方式共享暂存、预览、修正和人工确认边界；确认前不会写入正式内容或快照。 |
| analysis | 分析中心 | 找出还没分析或分析失败的作品，并查看问题和改进建议。 | 队列只展示服务端已经确认的分析状态、样本、Evidence 和置信度；不同平台分别筛选。 |
| accounts | 账号仪表盘 | 分账号查看运营状态；抖音和小红书的数据不会混在一起计算。 | 抖音与小红书账号分别展示，不进行跨平台指标合计。 |
| accountDashboard | 账号表现 | 只看这个账号的表现变化、目标完成情况和异常内容。 | 仅展示单个平台账号、同口径成熟度和满足样本门槛的服务端图表。 |
| columns | 栏目与活动 | 管理账号平时使用的栏目规则，以及活动期间临时使用的规则。 | 栏目和活动独立展示账号继承、临时覆盖、有效时间及当前版本。 |
| generation | 生成中心 | 根据已确认的事实、账号风格和参考内容，生成标题、文案和封面。 | 范围、事实、风格与参考、生成编辑和发布前复核依次完成；仅恢复不含正文、图片或凭据的安全元数据。 |
| preflight | 发布前检查 | 集中检查准备发布的内容，处理风险、图片文字识别和资料不足问题。 | 标题、正文和封面 OCR 的确定性规则与 RAG 辅助判断分开展示；无证据不代表安全通过。 |
| viralLibrary | 爆款素材库 | 保存确认过的优秀内容结构，之后生成内容时可以继续参考。 | 候选只表示单账号历史范围内的相对表现，人工确认后才成为可复用资产。 |
| styles | 账号风格 | 选择一个账号，查看并维护它常用的标题、文案和封面风格。 | 风格档案始终固定到单个平台账号，不提供全部账号合并视图。 |
| styleProfile | 账号风格中心 | 用人工确认的样本稳定账号表达；优秀内容结构不会自动变成账号风格。 | 最近内容和爆款只作为候选，只有人工选择并确认的版本才会生效。 |
| facts | 事实资料 | 保存商品、活动或选题中可以确认的事实，生成时用它减少写错和虚假宣传。 | 系统只约束生成内容与已确认资料一致，不证明资料本身客观真实。 |
| exports | 导出与备份 | 导出运营数据和分析报告，或备份整个工作区后再恢复。 | 所有文件通过异步任务生成；短期下载地址不写入浏览器存储，恢复必须先预览再确认。 |
| jobs | 后台任务 | 查看导入、分析、生成和备份等耗时任务有没有完成，失败后该怎么处理。 | 只展示状态、阶段和安全错误码，不展示任务正文、截图或模型响应。 |
| riskKnowledge | 风控知识库 | 管理平台规则资料；只有审核并生效的资料才会用于内容检查。 | 文档正文始终是不可信资料；扫描只使用已生效、已到生效日期的对应平台版本。 |
| trash | 回收站 | 恢复还在保留期内的内容；永久删除工作区要到设置中单独操作。 | 只展示支持软删除的内容资源；工作区删除使用独立影响预览和二次确认。 |
| settings | 工作区设置 | 管理成员、账号、模型费用限制和工作区安全操作。 | 统一展示工作区边界、权限和安全状态；所有变更仍由服务端权限和版本规则决定。 |
| settingsMembers | 成员与邀请码 | 给每个人创建独立邀请码、设置权限，并在成员离开时单独撤销。 | 坚持一人一码、一种角色；邀请码只显示一次且不写入 URL 或持久化存储。 |
| settingsModels | 模型配置 | 配置要使用的千问能力和每日费用上限；真实调用前请先确认地域和预算。 | 管理固定 Catalog、地域、实验状态、API Key、用量政策和受控真实验收。 |

For `preflight.safety`, use exactly:

```ts
safety: {
  simple: "没有查到规则资料不代表内容安全；图片文字识别不准或发现高风险时，必须人工检查，高风险内容不能发布。",
  professional: "无有效 Evidence 不等于安全通过；OCR 低置信度必须人工复核，RAG 不得降低确定性规则等级，高风险受发布门禁阻断。",
},
```

- [ ] **Step 4: Define exact role-aware guidance contracts**

Create `page-guidance-catalog.ts`:

```ts
import type { WorkbenchRole } from "./navigation";
import type { ModeAwareCopy, OperatorPageId } from "./operator-copy-catalog";

export type GuidanceAction = {
  kind: "read" | "write" | "contact";
  label: ModeAwareCopy;
};
export type PageGuidanceEntry = {
  nextByRole: Record<WorkbenchRole, GuidanceAction>;
  steps: readonly ModeAwareCopy[];
  concepts: readonly ModeAwareCopy[];
  blockers: readonly ModeAwareCopy[];
};
export function nextActionForRole(
  entry: PageGuidanceEntry,
  role: WorkbenchRole,
): GuidanceAction {
  return entry.nextByRole[role];
}
export const PAGE_GUIDANCE_CATALOG:
  Record<OperatorPageId, PageGuidanceEntry> = {
  // Each key listed in OPERATOR_PAGE_IDS is required by Record<>.
  // Use the exact actions, concepts, steps, and blockers specified below.
};
```

Every page gets 3–5 steps. Use this exact action matrix:

| ID | Admin next action | Editor next action | Viewer next action |
| --- | --- | --- | --- |
| overview | 处理系统列出的最高优先级事项 | 处理系统列出的最高优先级事项 | 查看账号状态和待分析内容 |
| contents | 新建内容或导入作品数据 | 新建内容或导入作品数据 | 筛选并打开一条内容 |
| contentDetail | 补充数据或处理风险 | 补充数据或处理风险 | 查看数据、分析和风险标签 |
| imports | 选择一种方式导入并检查预览 | 选择一种方式导入并检查预览 | 查看最近导入记录 |
| analysis | 选择一个平台并处理待分析内容 | 选择一个平台并处理待分析内容 | 筛选并查看已有分析结果 |
| accounts | 配置账号或打开单账号表现 | 打开一个账号查看表现 | 打开一个账号查看表现 |
| accountDashboard | 检查缺少的数据并处理异常内容 | 检查缺少的数据并处理异常内容 | 查看趋势、目标和异常说明 |
| columns | 新建或调整栏目规则 | 新建或调整栏目规则 | 查看当前生效规则 |
| generation | 选择平台、账号和栏目后开始生成 | 选择平台、账号和栏目后开始生成 | 查看已保存的生成结果 |
| preflight | 处理高风险和需要人工检查的内容 | 处理高风险和需要人工检查的内容 | 查看风险原因和判断依据 |
| viralLibrary | 确认一个候选为可复用参考 | 确认一个候选为可复用参考 | 查看已确认的优秀内容结构 |
| styles | 选择一个账号进入风格中心 | 选择一个账号进入风格中心 | 选择一个账号查看风格 |
| styleProfile | 选择样本并确认新版本 | 选择样本并确认新版本 | 查看当前生效风格和历史版本 |
| facts | 添加来源并确认可用于生成的事实 | 添加来源并确认可用于生成的事实 | 查看已确认事实和冲突说明 |
| exports | 创建需要的导出或备份 | 创建需要的导出或备份 | 联系管理员或编辑者创建文件 |
| jobs | 检查失败任务并按安全建议处理 | 查看失败任务并联系管理员处理 | 联系管理员或编辑者查看后台任务 |
| riskKnowledge | 审核待处理的平台规则资料 | 联系管理员审核或更新规则资料 | 联系管理员查看风控资料 |
| trash | 恢复仍在保留期内的内容 | 恢复仍在保留期内的内容 | 联系管理员或编辑者恢复内容 |
| settings | 检查成员、账号、模型和安全设置 | 联系管理员修改工作区设置 | 联系管理员修改工作区设置 |
| settingsMembers | 创建独立邀请码或检查成员权限 | 联系管理员管理成员和邀请码 | 联系管理员管理成员和邀请码 |
| settingsModels | 配置模型、预算并执行受控验收 | 联系管理员配置模型和费用上限 | 联系管理员配置模型和费用上限 |

For every Viewer entry that asks another role, set `kind: "contact"`; all other Viewer entries use `kind: "read"`. Admin/Editor mutation actions use `kind: "write"`.

Because next-action guidance did not exist in the old interface, use the same exact label for `simple` and `professional`; do not invent a second technical wording.

Use these exact three easy-mode steps for each page. Use the same step text in professional mode unless the step contains a concept from `sharedConcepts`; in that case substitute the professional concept text.

| ID | Step 1 | Step 2 | Step 3 |
| --- | --- | --- | --- |
| overview | 先看“数据状态”，确认哪些账号缺少发布后的数据。 | 再看“待处理问题”，确认有没有待分析、风险或失败任务。 | 按“下一步行动”只处理当前优先级最高的一项。 |
| contents | 选择平台和账号，再按栏目、状态或关键词筛选。 | 打开一条作品，查看数据、分析、风险和生成记录。 | 需要新增时创建内容，已有作品则导入发布后的数据。 |
| contentDetail | 在“概览”确认作品和发布状态。 | 在“数据快照、分析、风控”查看结果和缺失项。 | 有权限时补充数据、重新分析或重新检查风险。 |
| imports | 选择手动、表格、截图或浏览器扩展。 | 在预览中核对平台、账号、标题和运营数据。 | 修改错误后确认，系统才会写入正式记录。 |
| analysis | 先选择抖音或小红书，必要时再选账号。 | 筛选待分析、进行中、成功或失败状态。 | 打开作品查看问题和建议，有权限时重新分析。 |
| accounts | 先查看每个账号的数据完整度和待处理数量。 | 打开一个账号，避免把不同平台的数据混在一起。 | 根据账号页面提示补数据或处理异常内容。 |
| accountDashboard | 选择作品类型和数据采集时间。 | 查看目标、变化趋势、漏斗和异常候选。 | 根据“下一步行动”补数据或打开异常作品。 |
| columns | 选择一个平台账号。 | 查看账号默认规则和活动期间的临时规则。 | 修改后确认生效时间，并检查何时恢复默认。 |
| generation | 先选择平台、账号、栏目和生成目标。 | 核对事实，选择是否沿用账号风格和优秀内容参考。 | 生成并编辑后，再完成事实和发布风险检查。 |
| preflight | 选择平台和账号，筛选需要处理的状态。 | 打开一条内容，核对标题、正文和封面文字风险。 | 修改内容后重新检查，直到没有阻断问题。 |
| viralLibrary | 选择单个平台账号。 | 比较候选表现和系统给出的参考原因。 | 人工确认后，这条内容才能在生成时被引用。 |
| styles | 选择一个平台账号进入风格中心。 | 查看该账号是否已有生效风格和历史版本。 | 需要修改时选择样本、提取并确认新版本。 |
| styleProfile | 选择能代表账号的已发布内容作为样本。 | 分别检查标题、文案、封面和禁止项。 | 确认新版本后，后续生成才会默认沿用。 |
| facts | 添加网页来源或查看已有来源。 | 把可确认的信息整理成事实，并处理冲突。 | 只有已确认且没有冲突的事实才能稳定用于生成。 |
| exports | 选择 CSV、报告、JSON 或完整 ZIP。 | 创建任务并等待文件生成；恢复时先看预览。 | 下载文件或确认恢复前，再核对范围和冲突。 |
| jobs | 按任务类型和状态筛选。 | 查看失败发生在哪个阶段以及建议的处理方式。 | 管理员可取消或安全重试；其他角色联系管理员。 |
| riskKnowledge | 选择抖音或小红书，平台资料不能混用。 | 查看资料版本、来源等级和当前审核状态。 | 管理员审核并生效后，资料才会用于检查。 |
| trash | 查看仍在保留期内的已删除内容。 | 核对内容、删除时间和是否允许恢复。 | 有权限时恢复；永久删除工作区请前往设置。 |
| settings | 选择成员、账号、模型、保留策略或危险操作。 | 阅读当前权限和安全状态。 | 修改前确认影响；删除工作区必须再次确认。 |
| settingsMembers | 为新成员选择管理员、编辑者或查看者。 | 创建独立邀请码并立即安全交给本人。 | 成员离开时单独撤销，不影响其他成员。 |
| settingsModels | 选择固定模型能力和服务地域。 | 输入密钥并设置并发、次数和每日费用上限。 | 只有明确授权后才进行一次受控真实验收。 |

Use these exact reusable concepts and blockers where relevant:

```ts
const sharedConcepts = {
  maturity: {
    simple: "数据采集时间：这份数据是在作品发布后多久记录的。",
    professional: "数据成熟度：1h、24h、72h 或 7d。",
  },
  benchmark: {
    simple: "同类作品比较：和这个账号最近的同类作品比较。",
    professional: "动态基准：按平台、账号、内容类型和成熟度生成。",
  },
  confidence: {
    simple: "判断可靠程度：表示当前结论有多大把握。",
    professional: "置信度：由服务端分析合同返回。",
  },
  staged: {
    simple: "检查后再导入：预览和修改不会直接写进正式数据。",
    professional: "暂存预览：人工确认前不写正式内容或快照。",
  },
};
```

Each entry must include its exact blocker from this matrix:

| Page IDs | Easy blocker |
| --- | --- |
| overview, accounts | 还没有账号时，请先到工作区设置创建抖音或小红书账号。 |
| contents | 当前筛选没有作品；调整筛选，或由管理员/编辑者新建内容。 |
| contentDetail, accountDashboard, analysis | 还没有确认过的数据；先导入并确认一次发布后的表现数据。 |
| imports | 没有选择匹配的平台和账号时，数据不能正式导入。 |
| columns | 当前账号没有栏目时，可以继续使用账号默认规则。 |
| generation | 还没有完成模型和费用配置时，请联系管理员；未确认事实不能直接写进确定性文案。 |
| preflight | 暂时没有可用的平台规则资料不代表内容安全；图片文字识别不准时必须人工检查。 |
| viralLibrary | 候选没有经过人工确认时，生成内容不能引用它。 |
| styles, styleProfile | 没有人工选择并确认的样本时，系统不会自动生成生效风格。 |
| facts | 视觉判断不能证明面料、价格、功效或认证；冲突事实不能用于确定性生成。 |
| exports | 恢复前检查发现版本、文件或引用冲突时，正式数据不会被修改。 |
| jobs | 多次尝试仍失败或自动清理未完成时，需要管理员处理。 |
| riskKnowledge | 资料没有审核并生效时，不会参与内容风险判断。 |
| trash | 超过保留期或因审计要求被保留的内容，不能按普通恢复/删除处理。 |
| settings | 当前角色没有设置权限时，请联系管理员。 |
| settingsMembers | 邀请码创建后只显示一次；丢失后只能撤销并重新创建。 |
| settingsModels | 没有每日费用上限或明确授权时，系统不会发起真实模型调用。 |

Append `当前是查看权限；需要修改时请联系管理员或编辑者。` to the Viewer blockers for every page whose Viewer action is `contact`.

- [ ] **Step 5: Run catalog tests and verify GREEN**

Run the Step 2 command.

Expected: all catalog tests PASS.

- [ ] **Step 6: Run static checks**

```bash
pnpm --filter web lint
pnpm --filter web typecheck
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit**

```bash
git add \
  apps/web/src/components/workbench/operator-copy-catalog.ts \
  apps/web/src/components/workbench/page-guidance-catalog.ts \
  apps/web/src/components/workbench/operator-copy-catalog.test.ts
git commit -m "feat: define operator-friendly workbench copy"
```

---

### Task 3: Reusable Guided Header and Mode-Aware State Components

**Files:**
- Create: `apps/web/src/components/workbench/page-guide.tsx`
- Create: `apps/web/src/components/workbench/guided-page-header.tsx`
- Create: `apps/web/src/components/workbench/page-guide.test.tsx`
- Modify: `apps/web/src/components/workbench/ui.tsx`
- Modify: `apps/web/src/components/workbench/ui.test.tsx`

**Interfaces:**
- Consumes: `OperatorPageId`, catalogs, current role from `useWorkbenchShellContext`, and preferences from Task 1.
- Produces:
  - `PageGuide({ pageId }: { pageId: OperatorPageId })`
  - `GuidedPageHeader({ pageId, primaryAction?, secondaryActions? })`
  - `ModeAwareCopy` support in `Panel`, `EmptyState`, `ErrorState`, `PermissionNotice`, and `DesktopOnlyNotice`.

- [ ] **Step 1: Write failing guide rendering tests**

Create `page-guide.test.tsx`. Add this exact navigation and viewport setup, then define the context and helper:

```tsx
const navigationState = vi.hoisted(() => ({
  pathname: "/workspaces/workspace-1/analysis",
  search: "",
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => navigationState.pathname,
  useRouter: () => ({ replace: navigationState.replace }),
  useSearchParams: () => new URLSearchParams(navigationState.search),
}));

beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  });
});
```

```tsx
const context = {
  workspace_id: "workspace-1",
  workspace_name: "运营工作区",
  member_id: "member-1",
  member_display_name: "运营成员",
  role: "admin" as const,
  accounts: [],
  failed_task_count: 0,
};

function renderGuidance(
  pageId: OperatorPageId,
  role: "admin" | "editor" | "viewer",
) {
  return render(
    <WorkspaceShell context={{ ...context, role }}>
      <PageGuide pageId={pageId} />
    </WorkspaceShell>,
  );
}
```

Cover:

```tsx
test("always shows the easy purpose and expands persistent guidance", async () => {
  const user = userEvent.setup();
  renderGuidance("analysis", "editor");
  expect(screen.getByText(
    "找出还没分析或分析失败的作品，并查看问题和改进建议。",
  )).toBeVisible();
  expect(screen.getByText("建议先做")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "查看操作说明" }));
  expect(screen.getByRole("region", { name: "分析中心操作说明" })).toBeVisible();
  expect(screen.getByText("怎么使用")).toBeVisible();
  expect(screen.getByText("你会看到什么")).toBeVisible();
  expect(screen.getByText("常见情况")).toBeVisible();
});

test("keeps the purpose when guidance is off", () => {
  localStorage.setItem("operations-ai:page-guidance:member-1", "off");
  renderGuidance("contents", "viewer");
  expect(screen.getByText(
    "集中查看每条作品、发布状态、数据、分析和风险结果。",
  )).toBeVisible();
  expect(screen.queryByText("建议先做")).toBeNull();
  expect(screen.queryByRole("button", { name: "查看操作说明" })).toBeNull();
});

test("switches to the preserved professional purpose", () => {
  localStorage.setItem("operations-ai:copy-mode:member-1", "professional");
  renderGuidance("preflight", "admin");
  expect(screen.getByText(/OCR 的确定性规则与 RAG 辅助判断/)).toBeVisible();
});

test("gives viewers only read or contact guidance", () => {
  renderGuidance("settingsModels", "viewer");
  expect(screen.getByText("联系管理员配置模型和费用上限")).toBeVisible();
  expect(screen.queryByText("配置模型、预算并执行受控验收")).toBeNull();
});
```

- [ ] **Step 2: Extend shared UI tests for mode-aware copy**

Add the following test. Import `ExperiencePreferencesProvider`; seed one mode, render, clean up, seed the other mode, and render again so no undefined rerender helper is required:

```tsx
test("selects simple or professional state descriptions without changing semantics", () => {
  const state = (
    <EmptyState
      title="还没有数据"
      description={{
        simple: "先导入并确认一次发布后的数据。",
        professional: "缺少已确认的同口径快照。",
      }}
    />
  );
  localStorage.setItem("operations-ai:copy-mode:member-1", "simple");
  render(
    <ExperiencePreferencesProvider memberId="member-1">
      {state}
    </ExperiencePreferencesProvider>,
  );
  expect(screen.getByRole("status")).toHaveTextContent(
    "先导入并确认一次发布后的数据。",
  );

  cleanup();
  localStorage.setItem("operations-ai:copy-mode:member-1", "professional");
  render(
    <ExperiencePreferencesProvider memberId="member-1">
      {state}
    </ExperiencePreferencesProvider>,
  );
  expect(screen.getByRole("status")).toHaveTextContent(
    "缺少已确认的同口径快照。",
  );
});
```

Retain all existing string-prop tests unchanged to prove backwards compatibility.

- [ ] **Step 3: Run guide/UI tests and verify RED**

```bash
pnpm --filter web test:run -- \
  src/components/workbench/page-guide.test.tsx \
  src/components/workbench/ui.test.tsx
```

Expected: FAIL because the guide and mode-aware types do not exist.

- [ ] **Step 4: Implement mode-aware shared copy**

In `ui.tsx`, define:

```ts
import type { ModeAwareCopy } from "./operator-copy-catalog";
import { useOptionalExperiencePreferences } from "./experience-preferences-context";

export type DisplayCopy = string | ModeAwareCopy;

function DisplayText({ copy }: { copy: DisplayCopy }) {
  const preferences = useOptionalExperiencePreferences();
  const copyMode = preferences?.copyMode ?? "simple";
  return <>{typeof copy === "string" ? copy : copy[copyMode]}</>;
}
```

Change `description: string` to `description: DisplayCopy` in `PageHeader`, `Panel`, `EmptyState`, `ErrorState`, and the internal `StateMessage`. For shared fixed notices, add optional `description?: DisplayCopy` while preserving current fallback copy.

Do not change titles, ARIA roles, tone mapping, actions, or existing callers that pass a plain string.

- [ ] **Step 5: Implement `PageGuide`**

Create `page-guide.tsx`:

```tsx
"use client";

import { useState } from "react";
import { useExperiencePreferences } from "./experience-preferences-context";
import { copyForMode, OPERATOR_COPY_CATALOG, type OperatorPageId } from "./operator-copy-catalog";
import { PAGE_GUIDANCE_CATALOG, nextActionForRole } from "./page-guidance-catalog";
import { useWorkbenchShellContext } from "./workspace-shell";

export function PageGuide({ pageId }: { pageId: OperatorPageId }) {
  const [expanded, setExpanded] = useState(false);
  const context = useWorkbenchShellContext();
  const { copyMode, pageGuidance } = useExperiencePreferences();
  if (!context) throw new Error("PageGuide requires WorkspaceShell context");
  const page = OPERATOR_COPY_CATALOG[pageId];
  const guide = PAGE_GUIDANCE_CATALOG[pageId];
  const next = nextActionForRole(guide, context.role);
  const text = (value: { simple: string; professional: string }) =>
    copyForMode(value, copyMode);

  return (
    <section aria-label={`${page.title}页面说明`} className="mt-2 max-w-4xl">
      <p className="text-sm leading-6 text-[var(--text-secondary)]">
        {text(page.purpose)}
      </p>
      {page.safety ? (
        <p className="mt-2 text-sm font-medium text-amber-900" role="note">
          {text(page.safety)}
        </p>
      ) : null}
      {pageGuidance === "on" ? (
        <div className="mt-3 rounded-xl border border-blue-200 bg-blue-50 p-4 text-blue-950">
          <p className="text-sm">
            <strong>建议先做：</strong>{text(next.label)}
          </p>
          <button
            aria-expanded={expanded}
            className="mt-3 rounded-lg border border-blue-300 bg-white px-3 py-2 text-sm font-semibold"
            onClick={() => setExpanded((value) => !value)}
            type="button"
          >
            {expanded ? "收起操作说明" : "查看操作说明"}
          </button>
          {expanded ? (
            <div
              aria-label={`${page.title}操作说明`}
              className="mt-4 grid gap-4 lg:grid-cols-3"
              role="region"
            >
              <GuideList title="怎么使用" items={guide.steps.map(text)} />
              <GuideList title="你会看到什么" items={guide.concepts.map(text)} />
              <GuideList title="常见情况" items={guide.blockers.map(text)} />
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
```

Implement `GuideList` in the same file with a visible `h2` and ordered/unordered list; do not use `dangerouslySetInnerHTML`.

- [ ] **Step 6: Implement `GuidedPageHeader`**

Create `guided-page-header.tsx`:

```tsx
"use client";

import type { ReactNode } from "react";
import { OPERATOR_COPY_CATALOG, type OperatorPageId } from "./operator-copy-catalog";
import { PageGuide } from "./page-guide";
import { PageHeader, type DisplayCopy } from "./ui";

export function GuidedPageHeader({
  pageId,
  title,
  context,
  primaryAction,
  secondaryActions,
}: {
  pageId: OperatorPageId;
  title?: string;
  context?: DisplayCopy;
  primaryAction?: ReactNode;
  secondaryActions?: ReactNode;
}) {
  const page = OPERATOR_COPY_CATALOG[pageId];
  return (
    <div>
      <PageHeader
        description={context}
        primaryAction={primaryAction}
        secondaryActions={secondaryActions}
        title={title ?? page.title}
      />
      <PageGuide pageId={pageId} />
    </div>
  );
}
```

- [ ] **Step 7: Verify reusable components**

Run:

```bash
pnpm --filter web test:run -- \
  src/components/workbench/page-guide.test.tsx \
  src/components/workbench/ui.test.tsx \
  src/components/workbench/workspace-shell.test.tsx
pnpm --filter web lint
pnpm --filter web typecheck
```

Expected: all tests PASS and static checks exit 0.

- [ ] **Step 8: Commit**

```bash
git add \
  apps/web/src/components/workbench/page-guide.tsx \
  apps/web/src/components/workbench/guided-page-header.tsx \
  apps/web/src/components/workbench/page-guide.test.tsx \
  apps/web/src/components/workbench/ui.tsx \
  apps/web/src/components/workbench/ui.test.tsx
git commit -m "feat: add reusable operator page guidance"
```

---

### Task 4: Migrate Overview and Operations Pages

**Files:**
- Modify:
  - `apps/web/src/components/workbench/workbench-overview.tsx`
  - `apps/web/src/components/account/account-list.tsx`
  - `apps/web/src/components/charts/account-dashboard.tsx`
  - `apps/web/src/components/account/columns-center.tsx`
  - `apps/web/src/components/content/content-list.tsx`
  - `apps/web/src/components/content/content-detail-tabs.tsx`
  - `apps/web/src/components/imports/import-center.tsx`
  - `apps/web/src/components/analysis/analysis-queue.tsx`
- Test:
  - Existing colocated tests for all eight components.

**Interfaces:**
- Consumes: `GuidedPageHeader`, `DisplayCopy`, and catalog IDs from Tasks 2–3.
- Produces: complete easy/professional purpose and guidance coverage for overview, accounts, account dashboard, columns, contents, content detail, imports, and analysis.

- [ ] **Step 1: Add failing assertions to the existing eight test files**

For each component test, render under `WorkspaceShell` or the existing context helper and assert the easy purpose. Add these exact assertions:

```ts
expect(screen.getByText(
  "看清各账号目前缺什么数据、有哪些待处理内容，以及现在最值得先做哪一件事。",
)).toBeVisible();
expect(screen.getByText(
  "集中查看每条作品、发布状态、数据、分析和风险结果。",
)).toBeVisible();
expect(screen.getByText(
  "把作品和发布后的运营数据录入系统；确认前不会写入正式记录。",
)).toBeVisible();
expect(screen.getByText(
  "找出还没分析或分析失败的作品，并查看问题和改进建议。",
)).toBeVisible();
```

Use the corresponding exact catalog sentence for accounts, dashboard, columns, and content detail.

Add a professional-mode test for Analysis and Content Detail. Seed:

```ts
localStorage.setItem(
  "operations-ai:copy-mode:member-admin",
  "professional",
);
```

Then assert `Evidence 和置信度` for Analysis and `同口径快照` for Content Detail.

Add Viewer assertions that the displayed next action is read-only and existing write buttons remain absent.

- [ ] **Step 2: Run the eight component test files and verify RED**

```bash
pnpm --filter web test:run -- \
  src/components/workbench/workbench-overview.test.tsx \
  src/components/account/account-list.test.tsx \
  src/components/charts/charts.test.tsx \
  src/components/account/columns-center.test.tsx \
  src/components/content/content-list.test.tsx \
  src/components/content/content-detail-tabs.test.tsx \
  src/components/imports/import-center.test.tsx \
  src/components/analysis/analysis-queue.test.tsx
```

Expected: new purpose/guidance assertions FAIL.

- [ ] **Step 3: Replace top-level headers with exact page IDs**

Replace only the top-level `PageHeader` or custom `header` in each file:

| File | `pageId` |
| --- | --- |
| workbench-overview.tsx | `overview` |
| account-list.tsx | `accounts` |
| account-dashboard.tsx | `accountDashboard` |
| columns-center.tsx | `columns` |
| content-list.tsx | `contents` |
| content-detail-tabs.tsx | `contentDetail` |
| import-center.tsx | `imports` |
| analysis-queue.tsx | `analysis` |

Preserve existing dynamic titles, `primaryAction`, and `secondaryActions` exactly:

- Account dashboard passes `title={dashboard.account_name}` and:

```tsx
context={{
  simple: "数据按当前作品类型和数据采集时间分别计算。",
  professional: dashboard.explanation,
}}
```

- Content detail passes `title={content.title}` and keeps the current platform/account/column/lifecycle string as `context`.

Remove only the now-duplicated purpose description prop.

Example:

```tsx
<GuidedPageHeader
  pageId="contents"
  primaryAction={primaryAction}
  secondaryActions={role === "viewer" ? undefined : (
    <Link href={importHref}>导入作品数据</Link>
  )}
/>
```

- [ ] **Step 4: Convert representative states to outcome + reason + next action**

Use `ModeAwareCopy` on the following existing states:

```tsx
<EmptyState
  title="还没有作品"
  description={{
    simple: "先新建内容或导入作品数据；确认后，这里会显示发布状态、数据、分析和风险。",
    professional: "当前筛选范围没有正式内容记录；调整筛选条件，或创建第一条内容。",
  }}
/>
```

```tsx
<EmptyState
  title="还没有可分析的数据"
  description={{
    simple: "先导入并确认一次发布后的数据，再回到这里查看问题和建议。",
    professional: "当前没有满足分析门槛的已确认同口径快照。",
  }}
/>
```

```tsx
<EmptyState
  title="请选择平台和账号"
  description={{
    simple: "先选择抖音或小红书，再选择对应账号；两个平台的数据不会混在一起。",
    professional: "平台和账号共同决定指标、去重、栏目和正式写入范围。",
  }}
/>
```

For content risk failure, keep the safe code only in professional copy:

```tsx
description={{
  simple: "本次风险检查没有完成，不能当作安全通过。请重新检查或联系管理员。",
  professional: `安全错误码：${latest.error_code ?? "RISK_SCAN_FAILED"}；失败结果不会保存为成功扫描。`,
}}
```

Do not transform missing numeric values into zero and do not alter any API data mapping.

- [ ] **Step 5: Rename vague primary buttons where context is not sufficient**

Use these exact labels without changing callbacks:

- Content library: `新建内容` stays; `导入数据` becomes `导入作品数据`.
- Import confirmation: `确认` becomes `确认并正式写入`.
- Analysis retry: `重试` becomes `重新分析`.
- Risk retry in detail: `重新扫描` becomes `重新检查风险`.
- Generic `处理` links become `查看并处理`.

Do not rename tab labels or server states in data tables.

- [ ] **Step 6: Run migrated component tests**

Run the Step 2 command.

Expected: all tests PASS.

- [ ] **Step 7: Run Web regression and static checks**

```bash
pnpm --filter web test:run
pnpm --filter web lint
pnpm --filter web typecheck
pnpm --filter web build
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 8: Commit**

```bash
git add apps/web/src/components/{workbench,account,charts,content,imports,analysis}
git commit -m "feat: simplify workbench operations copy"
```

---

### Task 5: Migrate Creation and Strategy Asset Pages

**Files:**
- Modify:
  - `apps/web/src/components/workbench/generation-wizard.tsx`
  - `apps/web/src/components/risk/preflight-queue.tsx`
  - `apps/web/src/components/viral/viral-library.tsx`
  - `apps/web/src/components/styles/style-account-selector.tsx`
  - `apps/web/src/components/styles/style-profile-center.tsx`
  - `apps/web/src/components/facts/fact-source-center.tsx`
- Test:
  - `apps/web/src/components/workbench/generation-wizard.test.tsx`
  - `apps/web/src/components/risk/preflight-queue.test.tsx`
  - `apps/web/src/components/viral/viral-library.test.tsx`
  - `apps/web/src/components/styles/style-account-selector.test.tsx`
  - `apps/web/src/components/styles/style-profile-center.test.tsx`
  - `apps/web/src/components/facts/fact-source-center.test.tsx`

**Interfaces:**
- Consumes: guided headers and mode-aware states.
- Produces: operator copy for generation, preflight, viral library, styles, style profile, and facts without weakening fact/risk boundaries.

- [ ] **Step 1: Write failing easy/professional and safety assertions**

Add one easy-purpose assertion per page using the Task 2 catalog.

Add these safety assertions:

```ts
expect(screen.getByText(/没有查到规则资料不代表内容安全/)).toBeVisible();
expect(screen.getByText(/视觉判断不能证明面料、价格、功效或认证/)).toBeVisible();
expect(screen.getByText(/优秀内容结构不会自动变成账号风格/)).toBeVisible();
expect(screen.getByText(/候选.*确认.*才能.*参考/)).toBeVisible();
```

In professional mode, assert the existing terms `RAG`, `OCR`, `L5`, and `版本确认` remain available.

For Viewer tests, assert no next action contains “确认候选”“确认新版本”“添加来源” or “开始生成”.

- [ ] **Step 2: Run the six component test files and verify RED**

```bash
pnpm --filter web test:run -- \
  src/components/workbench/generation-wizard.test.tsx \
  src/components/risk/preflight-queue.test.tsx \
  src/components/viral/viral-library.test.tsx \
  src/components/styles/style-account-selector.test.tsx \
  src/components/styles/style-profile-center.test.tsx \
  src/components/facts/fact-source-center.test.tsx
```

Expected: new copy assertions FAIL.

- [ ] **Step 3: Replace headers with guided IDs**

| File | `pageId` |
| --- | --- |
| generation-wizard.tsx | `generation` |
| preflight-queue.tsx | `preflight` |
| viral-library.tsx | `viralLibrary` |
| style-account-selector.tsx | `styles` |
| style-profile-center.tsx | `styleProfile` |
| fact-source-center.tsx | `facts` |

For `style-profile-center.tsx`, replace the custom dark-style header with `GuidedPageHeader` and keep the “当前正在维护栏目/活动覆盖风格” status directly below it.

- [ ] **Step 4: Add exact easy/professional concept copy**

Use mode-aware descriptions for these concepts:

```ts
const visualFactWarning = {
  simple: "图片只能帮助识别可能出现的文字或外观，不能证明面料、价格、功效、认证等事实。",
  professional: "L5 视觉推断不能升级为已验证事实，也不能单独支撑确定性生成声明。",
};
const viralCandidateExplanation = {
  simple: "候选只是这个账号里相对表现较好的内容；人工确认后，生成时才能把它作为参考。",
  professional: "候选按单账号动态基准产生；未确认候选不得进入生成引用。",
};
const styleBoundary = {
  simple: "账号风格用于保持表达稳定；优秀内容结构只是参考，不会自动变成账号风格。",
  professional: "账号 Style Profile 与已确认 Viral Reference 保持独立版本和引用边界。",
};
const preflightNoEvidence = {
  simple: "暂时没有可用的平台规则资料，这不代表内容安全；请继续人工检查。",
  professional: "NO_ACTIVE_RISK_EVIDENCE：保留确定性结果，不生成虚假 Citation。",
};
```

Keep the fixed disclaimer “辅助判断，不保证通过平台审核” unchanged in both modes.

- [ ] **Step 5: Clarify generation steps without altering workflow**

Keep the five step names unchanged, but add one sentence below each:

1. 范围与目标：`先选择平台、账号和栏目，后面的事实、风格和参考只在这个范围内使用。`
2. 事实资料：`选择可以确认的资料；未确认或互相冲突的内容不能直接写进确定性文案。`
3. 风格与参考：`决定是否沿用账号风格，并选择最多三条已确认的优秀内容作为参考。`
4. 生成与编辑：`生成标题、文案和封面后可以修改；参考图片发送范围会在调用前说明。`
5. 复核与保存：`再次检查事实、风格和发布风险，通过后再保存。`

Do not change draft persistence, provider calls, input limits, facts, or preflight behavior.

- [ ] **Step 6: Verify page tests**

Run the Step 2 command.

Expected: all tests PASS.

- [ ] **Step 7: Run domain regression**

```bash
pnpm --filter web test:run
pnpm --filter web lint
pnpm --filter web typecheck
pnpm --filter web build
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 8: Commit**

```bash
git add apps/web/src/components/{workbench,risk,viral,styles,facts}
git commit -m "feat: explain creation and strategy assets"
```

---

### Task 6: Migrate Governance, Data, Jobs, and Settings

**Files:**
- Modify:
  - `apps/web/src/components/exports/export-backup-center.tsx`
  - `apps/web/src/components/operations/job-operations.tsx`
  - `apps/web/src/components/risk/risk-knowledge-center.tsx`
  - `apps/web/src/components/exports/trash-center.tsx`
  - `apps/web/src/components/workspace/workspace-settings.tsx`
  - `apps/web/src/components/workspace/member-settings.tsx`
  - `apps/web/src/components/models/model-config-form.tsx`
- Test:
  - Existing colocated tests for each component.

**Interfaces:**
- Consumes: guided headers, display copy, role guidance.
- Produces: operator-facing explanations for exports, jobs, risk knowledge, trash, workspace settings, members, and model configuration.

- [ ] **Step 1: Add failing copy and role assertions**

Add easy-purpose assertions for all seven surfaces.

Add exact behavior assertions:

```ts
expect(screen.getByText(
  "查看导入、分析、生成和备份等耗时任务有没有完成，失败后该怎么处理。",
)).toBeVisible();
expect(screen.getByText(
  "配置要使用的千问能力和每日费用上限；真实调用前请先确认地域和预算。",
)).toBeVisible();
expect(screen.getByText(/邀请码只在创建时显示一次/)).toBeVisible();
expect(screen.getByText(/永久删除工作区要到设置中单独操作/)).toBeVisible();
```

Professional mode must still expose safe terms such as `Readiness`, `安全错误码`, `experimental`, `Provider`, and `影响预览`; it must never expose an API key or invite code that the existing API does not return.

- [ ] **Step 2: Run management component tests and verify RED**

```bash
pnpm --filter web test:run -- \
  src/components/exports/export-backup-center.test.tsx \
  src/components/operations/job-operations.test.tsx \
  src/components/risk/risk-knowledge-center.test.tsx \
  src/components/exports/trash-center.test.tsx \
  src/components/workspace/workspace-settings.test.tsx \
  src/components/workspace/member-settings.test.tsx \
  src/components/models/model-config-form.test.tsx
```

Expected: new copy assertions FAIL.

- [ ] **Step 3: Replace or add guided headers**

| File | `pageId` |
| --- | --- |
| export-backup-center.tsx | `exports` |
| job-operations.tsx | `jobs` |
| risk-knowledge-center.tsx | `riskKnowledge` |
| trash-center.tsx | `trash` |
| workspace-settings.tsx | `settings` |
| member-settings.tsx | `settingsMembers` |
| model-config-form.tsx | `settingsModels` |

For files with custom `<h1>` blocks, replace the entire heading block with `GuidedPageHeader`, but preserve nearby status badges such as `experimental`.

- [ ] **Step 4: Translate internal states only in easy mode**

Use exact easy/professional mappings:

| Internal/professional | Easy |
| --- | --- |
| Readiness | 系统依赖状态 |
| dead_letter | 多次尝试仍失败，需要管理员处理 |
| compensation_required | 自动清理没有完成，需要管理员处理 |
| configuration_required | 还没有完成所需配置 |
| experimental | 试用状态，真实效果和费用尚未完成验收 |
| provider_outcome_unknown | 模型服务是否已经计费暂时无法确认，请勿直接重复提交 |
| ZIP restore preview | 完整备份恢复前检查 |
| retention evidence | 因审计或关联资料要求而保留，暂时不能删除 |

Implement a local display helper or a focused shared mapping in the owning file; do not replace the underlying state values used for filters or requests.

- [ ] **Step 5: Clarify destructive and secret-bearing actions**

Use these exact easy descriptions:

- Invite code: `邀请码只在创建时显示一次。请立即交给对应成员，不要发到公开群或截图保存到公共位置。`
- API key: `密钥保存后不会再次显示；更换密钥需要重新输入。`
- Real provider: `真实调用可能产生费用；没有设置每日上限时，系统不会允许调用。`
- ZIP restore: `系统会先检查版本、文件和冲突；确认恢复前不会改动正式数据。`
- Trash: `这里只恢复仍在保留期内的内容。永久删除整个工作区需要到设置中查看影响并再次确认。`

Keep existing server-side permissions and second-confirmation flows unchanged.

- [ ] **Step 6: Verify management tests**

Run the Step 2 command.

Expected: all tests PASS.

- [ ] **Step 7: Run complete Web regression**

```bash
pnpm --filter web test:run
pnpm --filter web lint
pnpm --filter web typecheck
pnpm --filter web build
pnpm schemas:check
pnpm metrics:check
git diff --check
```

Expected: all commands exit 0 and generated contracts show no drift.

- [ ] **Step 8: Commit**

```bash
git add apps/web/src/components/{exports,operations,risk,workspace,models}
git commit -m "feat: clarify workbench governance copy"
```

---

### Task 7: Role, Mobile, Visual, and Independent-User Acceptance

**Files:**
- Create: `tests/e2e/workbench-guidance.spec.ts`
- Modify: `tests/e2e/workbench-visual.spec.ts`
- Modify: `docs/acceptance/requirements-traceability.md`
- Modify: `docs/acceptance/non-developer-participant-task-card.md`
- Test snapshots:
  - `tests/e2e/workbench-visual.spec.ts-snapshots/guidance-easy-darwin.png`
  - `tests/e2e/workbench-visual.spec.ts-snapshots/guidance-professional-darwin.png`
  - `tests/e2e/workbench-visual.spec.ts-snapshots/guidance-off-darwin.png`
  - `tests/e2e/workbench-visual.spec.ts-snapshots/mobile-guidance-darwin.png`

**Interfaces:**
- Consumes: completed page migration and existing isolated E2E fixtures.
- Produces: automated acceptance evidence and a non-developer Task 9B task card.

- [ ] **Step 1: Write the failing Playwright acceptance**

Create `workbench-guidance.spec.ts` with these complete helpers:

```ts
import {
  expect,
  type APIRequestContext,
  type Page,
  test,
} from "@playwright/test";

const api = process.env.WORKBENCH_E2E_API_URL
  ?? `http://127.0.0.1:${process.env.WORKBENCH_E2E_API_PORT ?? "8100"}`;

type Workspace = {
  workspace_id: string;
  admin_code: string;
};

async function createWorkspace(
  request: APIRequestContext,
  name: string,
): Promise<Workspace> {
  const response = await request.post(`${api}/v1/workspaces`, {
    data: { name },
  });
  expect(response.ok()).toBeTruthy();
  return response.json() as Promise<Workspace>;
}

async function enterWorkspace(
  page: Page,
  workspace: Workspace,
  code: string,
  displayName: string,
) {
  await page.goto("/enter");
  await page.getByLabel("邀请码").fill(code);
  await page.getByLabel("显示名称").fill(displayName);
  await page.getByRole("button", { name: "进入工作区" }).click();
  await page.waitForURL(
    new RegExp(`/workspaces/${workspace.workspace_id}/`),
  );
}

async function issueCode(
  page: Page,
  workspaceId: string,
  role: "editor" | "viewer",
): Promise<string> {
  return page.evaluate(async ({ apiUrl, targetWorkspaceId, targetRole }) => {
    const response = await fetch(
      `${apiUrl}/v1/workspaces/${targetWorkspaceId}/members/codes`,
      {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": sessionStorage.getItem("workspace_csrf") ?? "",
        },
        body: JSON.stringify({ role: targetRole }),
      },
    );
    if (!response.ok) {
      throw new Error(`member code failed (${response.status})`);
    }
    return ((await response.json()) as { code: string }).code;
  }, {
    apiUrl: api,
    targetWorkspaceId: workspaceId,
    targetRole: role,
  });
}
```

Then add this exact flow:

```ts
test("operator copy and guidance persist without changing business state", async ({
  browser,
  page,
  request,
}) => {
  const workspace = await createWorkspace(request, "运营文案验收工作区");
  await enterWorkspace(page, workspace, workspace.admin_code, "文案管理员");
  await page.goto(`/workspaces/${workspace.workspace_id}/analysis`);

  await expect(page.getByRole("radio", { name: "易懂" })).toBeChecked();
  await expect(page.getByRole("switch", { name: "页面引导" })).toBeChecked();
  await expect(page.getByText(
    "找出还没分析或分析失败的作品，并查看问题和改进建议。",
  )).toBeVisible();

  const urlBefore = page.url();
  await page.getByRole("radio", { name: "专业" }).click();
  await expect(page.getByText(/Evidence 和置信度/)).toBeVisible();
  expect(page.url()).toBe(urlBefore);

  await page.reload();
  await expect(page.getByRole("radio", { name: "专业" })).toBeChecked();
  await page.getByRole("switch", { name: "页面引导" }).click();
  await expect(page.getByText(/Evidence 和置信度/)).toBeVisible();
  await expect(page.getByText("建议先做")).toHaveCount(0);

  await page.goto(`/workspaces/${workspace.workspace_id}/generation`);
  await page.getByLabel("生成目标").fill("测试发布目标");
  await page.getByRole("radio", { name: "易懂" }).click();
  await expect(page.getByLabel("生成目标")).toHaveValue("测试发布目标");
  await expect(page).toHaveURL(
    `/workspaces/${workspace.workspace_id}/generation`,
  );

  const viewerCode = await issueCode(page, workspace.workspace_id, "viewer");
  const viewer = await browser.newContext();
  const viewerPage = await viewer.newPage();
  await enterWorkspace(viewerPage, workspace, viewerCode, "文案查看者");
  await viewerPage.goto(`/workspaces/${workspace.workspace_id}/generation`);
  await expect(viewerPage.getByText("查看已保存的生成结果")).toBeVisible();
  await expect(viewerPage.getByText(/开始生成/)).toHaveCount(0);
  await viewer.close();
});
```

Add a 390px test:

```ts
test("390px keeps controls and expandable help accessible", async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const workspace = await createWorkspace(request, "移动引导验收工作区");
  await enterWorkspace(page, workspace, workspace.admin_code, "移动验收管理员");
  await page.goto(`/workspaces/${workspace.workspace_id}`);
  await page.getByText("界面说明", { exact: true }).click();
  await expect(page.getByRole("radiogroup", { name: "文案模式" })).toBeVisible();
  await page.getByText("界面说明", { exact: true }).click();
  await page.getByRole("button", { name: "查看操作说明" }).click();
  await expect(page.getByRole("region", { name: /操作说明/ })).toBeVisible();
  await expect(page.getByRole("main")).toHaveCount(1);
});
```

- [ ] **Step 2: Run the new E2E and verify RED**

Use the existing isolated workbench E2E command/environment from `scripts/verify-fresh-install.sh`, targeting:

```bash
pnpm --dir tests/e2e exec playwright test workbench-guidance.spec.ts
```

Expected: FAIL before the final integration is complete, or PASS if all prior tasks already satisfy the contract. If it passes immediately, record that the acceptance was written after the behavior and continue; do not weaken assertions.

- [ ] **Step 3: Add deterministic visual scenarios**

In `workbench-visual.spec.ts`, after the existing fixture is seeded:

```ts
await page.goto(`${root}/analysis?${scoped}`);
await capture(page, "guidance-easy.png");

await page.getByRole("radio", { name: "专业" }).click();
await capture(page, "guidance-professional.png");

await page.getByRole("switch", { name: "页面引导" }).click();
await capture(page, "guidance-off.png");

await page.setViewportSize({ width: 390, height: 844 });
await page.goto(`${root}/preflight?${scoped}`);
await page.getByRole("button", { name: "查看操作说明" }).click();
await capture(page, "mobile-guidance.png");
```

Ensure `prepareScreenshot` still removes UUID variability and does not hide the guidance controls.

- [ ] **Step 4: Run E2E, generate snapshots, and manually inspect all four**

Run in the isolated test environment:

```bash
pnpm --dir tests/e2e exec playwright test \
  workbench-guidance.spec.ts \
  workbench-navigation.spec.ts \
  workbench-mobile.spec.ts
pnpm --dir tests/e2e exec playwright test \
  workbench-visual.spec.ts --update-snapshots
```

Manual visual checks:

1. Purpose remains visible with guidance off.
2. Expanded guide does not push the page’s first action below an unusable fold.
3. Professional copy does not overflow the topbar or header.
4. 390px controls and guide do not overlap navigation or main content.
5. Status meaning is conveyed by text, not color alone.

- [ ] **Step 5: Update acceptance documentation**

Add a traceability row:

```md
| UX-COPY-01 | 运营用户可切换易懂/专业文案并随时开关页面引导；偏好按成员隔离，风险语义不弱化 | `experience-preferences.test.ts`, `operator-copy-catalog.test.ts`, `page-guide.test.tsx`, `workbench-guidance.spec.ts`, four visual baselines | automated_passed; independent_non_developer_pending |
```

Update the participant task card with exactly:

```md
## 页面理解任务

1. 保持“易懂”和“引导：开”，进入内容库，说出这个页面能做什么。
2. 展开“查看操作说明”，找到系统建议的下一步。
3. 关闭页面引导，确认仍能看到一句页面用途。
4. 切换到“专业”，说出你发现了哪些更专业的信息，然后切回“易懂”。
5. 进入发布前检查，说明“没有规则资料”“图片文字识别不准”“高风险”分别意味着什么。
6. 如果当前身份不能执行建议操作，说明页面让你联系谁。

主持人只记录，不解释术语、不指路、不代替点击。
```

- [ ] **Step 6: Run final verification**

```bash
pnpm --filter web test:run
pnpm --filter web lint
pnpm --filter web typecheck
pnpm --filter web build
pnpm schemas:check
pnpm metrics:check
pnpm secret:scan
git diff --check
```

Then run the repository’s isolated fresh-install verification:

```bash
bash scripts/verify-fresh-install.sh
```

Expected:

- Web unit/component tests: all PASS.
- Workbench guidance/navigation/mobile/visual E2E: all PASS.
- Fresh install and restart E2E: all PASS.
- No OpenAPI/schema/metric drift.
- Secret scan clean.
- Temporary Compose project, database, object data, network, and volumes removed by the verification script.

- [ ] **Step 7: Review against the approved spec**

Check every section of:

```text
docs/superpowers/specs/2026-08-01-operator-friendly-copy-guidance-design.md
```

Required review evidence:

- All 16 formal modules have a catalog entry and visible easy purpose.
- Content, account, style, member, and model detail surfaces are covered.
- All Viewer next actions are read/contact only.
- Easy primary copy contains no forbidden developer terms.
- Fixed safety disclaimers remain visible.
- No network request, URL, filter, form value, draft, or workflow state changes when preferences change.
- No API or migration diff.

- [ ] **Step 8: Commit**

```bash
git add \
  tests/e2e/workbench-guidance.spec.ts \
  tests/e2e/workbench-visual.spec.ts \
  tests/e2e/workbench-visual.spec.ts-snapshots \
  docs/acceptance/requirements-traceability.md \
  docs/acceptance/non-developer-participant-task-card.md
git commit -m "test: accept operator-friendly workbench guidance"
```
