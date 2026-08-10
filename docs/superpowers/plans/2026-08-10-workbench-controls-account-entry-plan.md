# Workbench Controls and Account Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify legacy workbench text/select controls with the approved light visual language and restore a discoverable, permission-safe account creation flow.

**Architecture:** Scope a reusable CSS form-control baseline to the private `WorkspaceShell`, leaving buttons and non-text controls explicit. Add one account creation panel to the account list page, backed by the existing typed account API, and route all new entry links to that single flow.

**Tech Stack:** Next.js 16, React 19, TypeScript, Tailwind CSS 4, OpenAPI-generated types, Vitest, Testing Library.

## Global Constraints

- Do not change database models, migrations, API contracts, permissions, Demo behavior, or real-provider boundaries.
- Admin and Editor may create accounts; Viewer remains read-only.
- Account creation defaults are `objectives: ["提升内容表现"]`, `metric_weights: { views: 1 }`, and `benchmark_sample_size: 30`.
- Preserve the untracked `.superpowers/brainstorm/` directory exactly as-is.
- Use test-driven development and do not push or merge.

---

### Task 1: Scoped workbench form-control baseline

**Files:**
- Modify: `apps/web/src/app/globals.css`
- Modify: `apps/web/src/components/workbench/workspace-shell.tsx`
- Modify: `apps/web/src/components/workbench/scope-filters.tsx`
- Test: `apps/web/src/components/workbench/workspace-shell.test.tsx`

**Interfaces:**
- Produces: `data-workbench-shell="true"` styling boundary and shared native text/select presentation.
- Consumes: existing Design Tokens and accessible labels.

- [ ] Add a failing shell regression test asserting the scope controls expose the workbench control marker and do not rely on legacy dark presentation.
- [ ] Run the focused test and confirm RED for the missing marker.
- [ ] Add the shell marker and scoped CSS for text-like inputs, textarea and select, including appearance, arrow, focus, placeholder and disabled states.
- [ ] Run the focused test and confirm GREEN.
- [ ] Run `rg` to confirm no workbench text/select control can remain visually near-black because of legacy classes.

### Task 2: Account creation client and single creation panel

**Files:**
- Modify: `apps/web/src/lib/account-api.ts`
- Create: `apps/web/src/components/account/account-create-panel.tsx`
- Create: `apps/web/src/components/account/account-create-panel.test.tsx`
- Modify: `apps/web/src/components/account/account-list.tsx`
- Modify: `apps/web/src/components/account/account-list.test.tsx`

**Interfaces:**
- Produces: `createAccount(workspaceId, csrfToken, input)` and `AccountCreatePanel`.
- Consumes: generated `AccountCreate`/`AccountRead`, sessionStorage CSRF, existing account route.

- [ ] Write failing tests for platform/name submission, fixed defaults, disabled duplicate submission, safe failure, successful scoped navigation and Viewer absence.
- [ ] Run focused tests and verify RED because the client and panel do not exist.
- [ ] Implement the typed client and minimal panel.
- [ ] Integrate the panel into the account list page behind `?action=create` for Admin/Editor.
- [ ] Run focused tests and verify GREEN.

### Task 3: Multiple discoverable entry points

**Files:**
- Modify: `apps/web/src/components/workbench/scope-filters.tsx`
- Modify: `apps/web/src/components/workbench/workspace-topbar.tsx`
- Modify: `apps/web/src/components/workbench/workspace-shell.test.tsx`
- Modify: `apps/web/src/components/workspace/workspace-settings.tsx`
- Modify: `apps/web/src/components/workspace/workspace-settings.test.tsx`

**Interfaces:**
- Produces: safe internal links to `/workspaces/{workspaceId}/accounts?action=create`.
- Consumes: current workspace ID and member role.

- [ ] Write failing tests for Admin/Editor topbar/account-page entry, Admin settings entry and Viewer hiding.
- [ ] Run focused tests and confirm RED.
- [ ] Add the links without duplicating the form or bypassing server authorization.
- [ ] Run focused tests and confirm GREEN.

### Task 4: Regression and visual acceptance

**Files:**
- Modify only if a regression reveals an in-scope defect.

**Interfaces:**
- Consumes: completed Tasks 1-3.
- Produces: verified local test build.

- [ ] Run the complete Web test suite.
- [ ] Run ESLint, TypeScript and production build.
- [ ] Rebuild/restart only the isolated local test Compose project, preserving its volumes.
- [ ] Inspect topbar, account page, a legacy form page and Viewer behavior in the browser.
- [ ] Confirm no dark legacy controls, all creation entrances are discoverable, account creation works, and no Viewer write action appears.
- [ ] Run `git diff --check` and inspect the final diff without touching `.superpowers/brainstorm/`.
