# Workspace Session Resume and Empty Account Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a valid same-browser workspace session return to its original team after a local service restart, and give an empty Admin/Editor overview a direct “创建账号” action.

**Architecture:** Add one focused browser recovery module that persists a strictly validated workspace/member/CSRF envelope and verifies it against the existing workbench context API before navigation. Reuse the existing account creation page and `action=create` query instead of adding new account APIs or forms.

**Tech Stack:** Next.js App Router, React 19, TypeScript, Vitest, Testing Library, existing generated OpenAPI client.

## Global Constraints

- Do not add a database migration or new authentication endpoint.
- Do not delete, merge, enumerate, or guess existing workspaces.
- Keep the existing 14-day HttpOnly session Cookie lifetime unchanged.
- Store no Session Cookie, invite code, display name, business content, model key, or platform data in the recovery record.
- Only Admin/Editor may see account creation actions; Viewer remains read-only.
- Do not implement cross-device login, recovery codes, email, phone, passwords, or third-party login.
- Preserve unrelated untracked files and do not inspect or modify `.superpowers/brainstorm/`.

---

### Task 1: Versioned Browser Recovery Record

**Files:**
- Create: `apps/web/src/lib/workspace-session-recovery.ts`
- Create: `apps/web/src/lib/workspace-session-recovery.test.ts`

**Interfaces:**
- Produces: `WorkspaceSessionRecoveryRecord` with `version: 1`, `workspaceId`, `memberId`, and `csrfToken`.
- Produces: `readWorkspaceSessionRecovery(storage: Storage): WorkspaceSessionRecoveryRecord | null`.
- Produces: `writeWorkspaceSessionRecovery(storage: Storage, record: Omit<WorkspaceSessionRecoveryRecord, "version">): void`.
- Produces: `clearWorkspaceSessionRecovery(storage: Storage): void`.
- Produces: `restoreWorkspaceCsrf(sessionStorage: Storage, record: WorkspaceSessionRecoveryRecord): void`.

- [ ] **Step 1: Write failing storage contract tests**

Create tests that require a round trip, reject malformed JSON, unknown versions, non-UUID IDs, short/blank CSRF values, and extra fields, and clear only the recovery key:

```ts
test("round-trips a valid versioned recovery record", () => {
  writeWorkspaceSessionRecovery(localStorage, {
    workspaceId: "019fee9a-cb94-79b3-a0f0-3d6116c33d1d",
    memberId: "019fee9a-cb95-70ab-8b01-123456789abc",
    csrfToken: "csrf-token-with-sufficient-length",
  });
  expect(readWorkspaceSessionRecovery(localStorage)).toMatchObject({
    version: 1,
    workspaceId: "019fee9a-cb94-79b3-a0f0-3d6116c33d1d",
  });
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `pnpm --filter web test:run -- src/lib/workspace-session-recovery.test.ts`

Expected: FAIL because `workspace-session-recovery.ts` does not exist.

- [ ] **Step 3: Implement strict parsing and storage helpers**

Use one constant key, `operations-ai:workspace-session-recovery:v1`. Parse JSON as `unknown`, require exactly `version`, `workspaceId`, `memberId`, and `csrfToken`, validate both IDs with a UUID expression, require a bounded CSRF string, and remove invalid records immediately. `restoreWorkspaceCsrf` writes only `workspace_csrf` to the supplied session storage.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `pnpm --filter web test:run -- src/lib/workspace-session-recovery.test.ts`

Expected: all recovery storage tests PASS with no console warnings.

- [ ] **Step 5: Commit Task 1**

```bash
git add apps/web/src/lib/workspace-session-recovery.ts apps/web/src/lib/workspace-session-recovery.test.ts
git commit -m "feat: persist safe workspace recovery state"
```

### Task 2: Resume the Existing Team from `/enter`

**Files:**
- Modify: `apps/web/src/app/enter/page.tsx`
- Modify: `apps/web/src/app/enter/page.test.tsx`
- Modify: `apps/web/src/components/workbench/workspace-shell.tsx`
- Modify: `apps/web/src/components/workbench/workspace-shell.test.tsx`

**Interfaces:**
- Consumes: Task 1 recovery helpers.
- Consumes: `loadWorkbenchContext(workspaceId, signal)` and `WorkbenchApiError.status` from `apps/web/src/lib/workbench-api.ts`.
- Produces: an entry state machine with `checking`, `entry`, and `retry` states.

- [ ] **Step 1: Write failing entry recovery tests**

Extend the entry page tests to prove:

```ts
test("returns a remembered valid member to the original workspace", async () => {
  writeWorkspaceSessionRecovery(localStorage, rememberedSession);
  mockedLoadWorkbenchContext.mockResolvedValue({
    workspace_id: rememberedSession.workspaceId,
    member_id: rememberedSession.memberId,
    role: "admin",
    accounts: [],
  });
  render(<EnterPage />);
  await waitFor(() => expect(window.location.assign).toHaveBeenCalledWith(
    `/workspaces/${rememberedSession.workspaceId}`,
  ));
  expect(sessionStorage.getItem("workspace_csrf")).toBe(rememberedSession.csrfToken);
});
```

Add separate tests for `401`/`404` clearing the record, context identity mismatch clearing the record, a network failure preserving the record and showing “返回上次团队”, and create/join success writing the recovery record.

- [ ] **Step 2: Write a failing shell expiry cleanup test**

Require a `401` from `loadWorkbenchContext` to clear both the versioned recovery record and `workspace_csrf`, while preserving unrelated local storage preferences.

- [ ] **Step 3: Run focused tests and verify RED**

Run: `pnpm --filter web test:run -- src/app/enter/page.test.tsx src/components/workbench/workspace-shell.test.tsx`

Expected: FAIL because `/enter` does not read or validate recovery state and the shell does not clear it.

- [ ] **Step 4: Implement the entry state machine**

On mount, read the recovery record. If absent, render the existing create/join entry immediately. If present, restore `workspace_csrf`, load the exact workspace context, require matching workspace and member IDs, then navigate. Treat `401`, `404`, and identity mismatch as invalid; clear recovery state and show the entry. Treat connection/dependency failures as retryable; retain the record and render a clear “返回上次团队” action plus an explicit “使用其他方式进入” action.

After successful create or invite join, write the recovery record before navigation. Keep the existing pending lock and mode-specific error copy.

- [ ] **Step 5: Clear recovery state on authenticated shell expiry**

In the existing `401` branch, call `clearWorkspaceSessionRecovery(window.localStorage)` and remove `workspace_csrf` from session storage in addition to the existing navigation/experience preference cleanup.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `pnpm --filter web test:run -- src/app/enter/page.test.tsx src/components/workbench/workspace-shell.test.tsx`

Expected: all new and existing entry/shell tests PASS.

- [ ] **Step 7: Commit Task 2**

```bash
git add apps/web/src/app/enter/page.tsx apps/web/src/app/enter/page.test.tsx apps/web/src/components/workbench/workspace-shell.tsx apps/web/src/components/workbench/workspace-shell.test.tsx
git commit -m "fix: resume valid workspace sessions"
```

### Task 3: Direct Empty-Overview Account Creation

**Files:**
- Modify: `apps/web/src/components/workbench/workbench-overview.tsx`
- Modify: `apps/web/src/components/workbench/workbench-overview.test.tsx`

**Interfaces:**
- Produces: Admin/Editor empty-state link `/workspaces/{workspaceId}/accounts?action=create` with accessible name `创建账号`.
- Preserves: Viewer empty-state with no account creation link.

- [ ] **Step 1: Write failing empty-state CTA tests**

Require the Admin/Editor empty overview to expose the direct link and Viewer to expose none:

```ts
expect(screen.getByRole("link", { name: "创建账号" })).toHaveAttribute(
  "href",
  "/workspaces/workspace-1/accounts?action=create",
);
```

- [ ] **Step 2: Run focused test and verify RED**

Run: `pnpm --filter web test:run -- src/components/workbench/workbench-overview.test.tsx`

Expected: FAIL because the current action is named “配置平台账号” and links to `/settings`.

- [ ] **Step 3: Implement the direct CTA**

Change only the non-Viewer empty-state action label and href. Keep the top `ScopeFilters` “＋ 创建账号” link and existing account form unchanged.

- [ ] **Step 4: Run focused test and verify GREEN**

Run: `pnpm --filter web test:run -- src/components/workbench/workbench-overview.test.tsx`

Expected: the overview tests PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add apps/web/src/components/workbench/workbench-overview.tsx apps/web/src/components/workbench/workbench-overview.test.tsx
git commit -m "fix: link empty overview to account creation"
```

### Task 4: Full Verification and Local Runtime Acceptance

**Files:**
- Verify only; do not modify user data or Docker volumes.

**Interfaces:**
- Consumes: completed Tasks 1–3.
- Produces: test and runtime evidence for the user.

- [ ] **Step 1: Run Web verification**

Run:

```bash
pnpm --filter web test:run
pnpm --filter web lint
pnpm --filter web typecheck
pnpm --filter web build
git diff --check
```

Expected: all commands PASS.

- [ ] **Step 2: Rebuild only the current Web image**

Use the existing `operations_ai_local_task8_20260807` Compose project and its existing volumes. Build the Web image, recreate `web`, and do not run `down --volumes`, `rm`, or any cleanup that targets persistent data.

- [ ] **Step 3: Verify health and behavior**

Check `http://127.0.0.1:51200/enter` and `http://127.0.0.1:51201/health/ready` return `200`. In a browser session, verify that a valid remembered workspace returns to the same workspace ID and that an empty Admin overview exposes the direct “创建账号” action.

- [ ] **Step 4: Record final repository state**

Run `git status --short` and report the three implementation commits plus the existing design and plan commits. Do not stage or commit unrelated untracked files.
