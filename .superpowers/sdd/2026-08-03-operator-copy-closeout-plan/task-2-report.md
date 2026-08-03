# Task 2 report: Viewer guidance closeout

Status: `IMPLEMENTED_WITH_EXTERNAL_E2E_BLOCKERS`

## Root cause and boundary

`importHistoryActionCopy()` had a Viewer-only fallback that turned the review
action into `Viewer 只读继续确认`, which reads like a Viewer can continue a
confirmation. Its Easy-mode review label also omitted the required contact
instruction; `retry` similarly omitted its contact-only boundary. The
Admin/Editor early-return branch was not changed. No API, request, permission,
state, URL, or business-rule code changed.

The Viewer mapping is now deliberately narrow:

- `review` is read/contact-only in Easy and Professional modes.
- `retry` lets a Viewer read the failure and directs retry to Admin/Editor.
- `wait` and `open_result` retain their existing viewing-only wording.
- Admin and Editor still receive their exact original action labels.

## RED / GREEN evidence

The initial literal focused command could not start because the desktop shell
provided `pnpm` without `node` (`exit 127`, `vitest: exec: node: not found`).
Rerunning with the bundled Codex Node binary on `PATH` provided the actual RED:

- `review` returned `{ simple: "查看等待确认的导入记录", professional: "Viewer 只读继续确认" }`;
- `retry` returned `{ simple: "查看失败", professional: "Viewer 只读查看失败" }`;
- the rendered Easy/Professional Viewer contracts failed for those exact
  missing strings.

After the minimal Viewer-only mapping, the declared focused command passed:

```text
Test Files  2 passed (2)
Tests       18 passed (18)
```

The full Web suite also passed: 46 files, 263 tests.

## Static verification

- `pnpm --filter web lint`: passed.
- `pnpm --filter web typecheck`: passed.
- `pnpm --filter web build`: passed.
- `pnpm schemas:check`: passed (no schema drift).
- `pnpm metrics:check`: passed (no metric drift).
- `pnpm secret:scan`: `secret_scan=clean`.
- `git diff --check`: passed.

## E2E, visual, and fresh-install status

The declared local Playwright command was attempted first. It failed before a
test ran because its API web-server prerequisite could not connect to
`localhost:55432` (PostgreSQL connection refused). Compose resolved the
binding, and the database was healthy in-container, but Docker reported no
runtime host-port mapping. The default database container was returned to its
prior stopped state.

The successful isolated topology used the same hostname across randomized host
ports: Web at `host.docker.internal:39123`, API at
`host.docker.internal:38123`, and API `WEB_ORIGIN` exactly matching the Web
origin. The runner used `docker compose run --rm --no-deps`, so it did not
recreate the checked stack. The product E2E executed: 6/7 passed, including
both guidance tests (therefore the new Professional Viewer import contract) and
the mobile tests. The one failure was outside Task 2: the existing navigation
matrix timed out after 30 seconds in `enterWorkspace()` waiting for a Viewer
post-invite URL, before its navigation assertions. A retry reproduced it.

The visual update run completed in the disposable Linux runner, but its
no-update rerun failed because the repository contains no committed
`*-linux.png` baselines (38 missing snapshots), not because of a pixel diff.
Those generated Linux candidates were isolated inside the removed runner and
were not added to the repository. The fixture contains no reviewable import,
so no visual fixture/snapshot change was fabricated.

The temporary `tests/e2e/workbench-isolated.playwright.config.ts` used for the
same-site run was removed and is not part of this task.

`bash scripts/verify-fresh-install.sh` was also attempted. It created its
random project, exited during the isolated build stage before its success
marker, and removed the project/resources. A follow-up Compose check found no
`operations_ai_task7_96369_23945` resources. Fresh-install/restart therefore
remains external-runtime blocked, with cleanup confirmed.

## Declared-surface literal audit

The exact `rg` scan was run. All remaining hits are classified as allowed:

- **Professional branches:** the six declared Task 1 surfaces use explicit
  `copyMode` / `displayText` branches, with focused Easy-mode no-leak tests
  included in the full 263-test pass.
- **Security disclosures:** import/export/settings messages accurately name
  excluded OCR content, vectors, prompts, worker runtime, or provider metadata
  to state a non-disclosure boundary.
- **Tests:** fixtures/assertions intentionally contain the professional terms
  and assert that Easy mode omits them.
- **Outside the six declared surfaces:** demo, cover-editor, model-management,
  standalone risk-report, extension/screenshot review, and unrelated support
  components were not part of Task 1's approved scope.

No unconditional primary Easy-mode match was found in the six approved
surfaces. This task's new Viewer copy does not add any scan term.

## Acceptance status and external pending items

`docs/acceptance/requirements-traceability.md` now records the Professional
Viewer import read/contact automation while preserving `UX-COPY-01` as
`partial`. Task 9B remains `independent_non_developer_pending`; no claim that
it passed is made.

External-only pending: resolve the unrelated Viewer-invite navigation timeout,
establish/commit the intended Linux visual baselines (or run on the baseline
platform), and complete `scripts/verify-fresh-install.sh` in the current Docker
environment.
