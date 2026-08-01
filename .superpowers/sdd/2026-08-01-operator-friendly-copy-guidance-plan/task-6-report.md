# Task 6 Report: Governance, Data, Jobs, and Settings

## Status

PASS. Migrated exports, jobs, risk knowledge, trash, workspace settings, members, and model configuration to guided, mode-aware operator copy without changing service contracts or permission behavior.

## TDD evidence

### RED

Command:

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

Result: exit 1. Ten expected assertions failed across all seven target files because guided purposes, easy state labels, and exact secret/destructive guidance were not yet rendered. The run had no test setup or runtime errors; unrelated existing tests passed.

### GREEN

The same focused command exited 0: 45 test files passed, 225 tests passed. In this repository the script's argument forwarding still executes the complete Web suite, so the focused command also supplied an early full-regression pass.

## Files changed

- `apps/web/src/components/exports/export-backup-center.tsx`
- `apps/web/src/components/exports/export-backup-center.test.tsx`
- `apps/web/src/components/operations/job-operations.tsx`
- `apps/web/src/components/operations/job-operations.test.tsx`
- `apps/web/src/components/risk/risk-knowledge-center.tsx`
- `apps/web/src/components/risk/risk-knowledge-center.test.tsx`
- `apps/web/src/components/exports/trash-center.tsx`
- `apps/web/src/components/exports/trash-center.test.tsx`
- `apps/web/src/components/workspace/workspace-settings.tsx`
- `apps/web/src/components/workspace/workspace-settings.test.tsx`
- `apps/web/src/components/workspace/member-settings.tsx`
- `apps/web/src/components/workspace/member-settings.test.tsx`
- `apps/web/src/components/models/model-config-form.tsx`
- `apps/web/src/components/models/model-config-form.test.tsx`
- `.superpowers/sdd/2026-08-01-operator-friendly-copy-guidance-plan/task-6-report.md`

## Verification

- Focused seven-component command: PASS, exit 0, 45 files / 225 tests.
- `pnpm --filter web test:run`: PASS, exit 0, 45 files / 225 tests.
- `pnpm --filter web lint`: PASS, exit 0.
- `pnpm --filter web typecheck`: PASS, exit 0.
- `pnpm --filter web build`: PASS, exit 0; production build compiled and generated all routes.
- `pnpm schemas:check`: PASS, exit 0; no OpenAPI/shared schema drift.
- `pnpm metrics:check`: PASS, exit 0; no generated metrics drift.
- `git diff --check`: PASS.

## Self-review

- One `h1`: each runtime branch uses exactly one `GuidedPageHeader`. Bespoke `h1` blocks were removed; the jobs permission and readable branches are mutually exclusive and each renders one header.
- Role safety: viewer/member/job/export/trash/model tests still assert the absence of mutation controls. Admin-only restore, task mutation, risk governance, workspace deletion, member management, model credential, and budget controls retain their original predicates.
- Secrets: API keys remain password inputs, clear after save, and are never read back. Invite codes are only rendered from the create response and the warning now states their one-time nature. Confirmation tokens remain in component memory and are never rendered, persisted, logged, or placed in URLs. No suppressed API key, invite code, or confirmation value was added to fixtures or display copy.
- Destructive copy: ZIP restoration still requires preview followed by explicit confirmation. Workspace deletion still requires impact loading, server-issued one-time confirmation, and final confirmation; the final action is not available before the prior steps. Trash explicitly redirects permanent workspace deletion to settings.
- Business logic: no service/API function, request argument, filter value, status predicate, permission predicate, daily budget field, destructive sequence, or secret-handling branch changed. Easy mode maps returned internal values only at render/message time; professional mode preserves `Readiness`, safe error codes, `experimental`, `Provider`, and impact-preview terminology.

## Concerns

- No product or safety blocker found.
- The required focused command currently runs all 45 Web test files because of the existing `test:run` script argument behavior; it is slower than a truly focused run but passed consistently.

## Review fix round 1

### Findings addressed

- Added mode-aware model configuration cards for loaded and newly saved configurations. Easy mode translates `experimental`, `not_run`, unavailable/failed states, and safe error codes into operator guidance; professional mode preserves exact status and code values.
- Added the guided page header to the production no-role operations-access loading branch, so that branch renders exactly one `h1`.
- Made export-history error terminology, workspace deletion impact success/fallback notices, and model Provider post-action/accessibility copy mode-aware.
- Extended destructive-flow coverage through ZIP preview → explicit confirmation and workspace impact → one-time confirmation → final deletion mutation. Tests assert that manifest fingerprints and one-time confirmation tokens are not rendered.

### TDD evidence

The four affected test files were run before production changes. The RED run failed on eight expected reviewed behaviors: two export terminology assertions, the no-role jobs heading, three model display/accessibility assertions, and two deletion-impact notice assertions. After implementation, the same command passed with 45 files and 233 tests.

### Verification

- Seven Task 6 component tests: PASS, exit 0, 45 files / 233 tests.
- `pnpm --filter web test:run`: PASS, exit 0, 45 files / 233 tests.
- `pnpm --filter web lint`: PASS, exit 0.
- `pnpm --filter web typecheck`: PASS, exit 0.
- `pnpm --filter web build`: PASS, exit 0.
- `pnpm schemas:check`: PASS, exit 0; no schema drift.
- `pnpm metrics:check`: PASS, exit 0; no metrics drift.
- `git diff --check`: PASS.

### Remaining risks

- No known product, permission, secret-handling, or destructive-order risk remains from the round 1 findings.
- Deferred minor items remain unchanged as requested: viewer rerender tests keep their existing shell-context setup, and the professional export purpose retains its existing duplicated sentence.
