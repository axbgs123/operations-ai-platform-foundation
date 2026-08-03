# Final fix report: operator-friendly copy and guidance

Date: 2026-08-03

Review base: `e60e12da2ae988276bb7128c9a73492c2a34f094`

Status: `DONE_WITH_CONCERNS`

The implementation and automated acceptance work in this fix wave are complete.
The feature remains `partial`, not production-complete, because the required
independent non-developer Task 9B session is an external acceptance boundary and
is still pending.

## Review findings resolved

### Easy mode covers populated and state content

- Added `operator-display-copy.ts` as the centralized render-time mapping layer
  for confidence, task/adoption state, preflight status and evidence, risk
  severity/type/origin/region/node, internal versions, provider/model
  capabilities, OCR, maturity, source/conflict, and import-method language.
- Migrated the required populated tables, cards, detail panels, empty states,
  and error states in content detail, preflight, account dashboard, workspace
  settings, model settings/status, overview, facts, and imports.
- Easy mode now uses accurate operator language and hides internal identifiers.
  Professional mode retains the existing verified technical terms and values.
- High-risk, missing-evidence, data-quality, model-cost, and destructive-impact
  meanings remain explicit; only display wording changes.

### Viewer next steps are read-only

- Role-mapped page-level, empty-state, and server-provided next actions on
  preflight, overview, account dashboard, facts, and imports.
- Viewer copy only permits reading, understanding, or contacting an authorized
  member. Admin and Editor actions remain available where already authorized.
- Added populated and empty Viewer coverage on affected surfaces.

### State branches retain page semantics

- Added the shared `GuidedPageShell` and used it for the required loading,
  permission, dependency-failure, error, and empty branches.
- Covered branches retain exactly one H1, the mode-aware purpose sentence, and
  the reopenable guide. Guidance-off tests confirm that the purpose remains.

### Minor findings

- Preference request invariance now records every business API request method,
  not only mutations.
- Added deterministic Viewer-permission and failed-dashboard visual states.
- Updated `requirements-traceability.md` to the allowed status vocabulary,
  validation date 2026-08-03, automated-pass evidence, and explicit Task 9B
  limitation. `UX-COPY-01` is `partial`.

## TDD evidence

### Initial RED

Focused component tests were added before the implementation changes for the
eight affected test surfaces. The expected RED run reported 8 failing files,
23 failing assertions, and 41 passing assertions. Failures demonstrated the
unmapped easy-mode terms, unsafe Viewer instructions, and missing page semantics
in state branches.

### Initial GREEN

The same eight focused files passed after implementation: 8 files and 64 tests.

### Bounded leak audit RED/GREEN

A subsequent literal audit found internal version identifiers and raw risk
severity still visible in content/preflight. Assertions were added first and
failed as expected in 2 files. After extending the centralized display mapping,
the bounded rerun passed: 2 files and 20 tests.

## Final verification

All commands used the repository-pinned Node/pnpm runtime.

- `pnpm --filter web test:run` — PASS, 45 files / 244 tests.
- `pnpm --filter web lint` — PASS.
- `pnpm --filter web typecheck` — PASS after Next route type generation.
- `pnpm --filter web build` — PASS; production Next build completed.
- `pnpm schemas:check` — PASS; no generated schema drift.
- `pnpm metrics:check` — PASS; no generated metric drift.
- `pnpm secret:scan` — PASS; no secret finding.
- `git diff --check` — PASS.
- `pnpm --dir tests/e2e exec playwright test workbench-guidance.spec.ts workbench-navigation.spec.ts workbench-mobile.spec.ts` — PASS, 7/7, including all-method business-request invariance.
- `pnpm --dir tests/e2e exec playwright test workbench-visual.spec.ts --update-snapshots --timeout=120000` — PASS, 1/1.
- `pnpm --dir tests/e2e exec playwright test workbench-visual.spec.ts --timeout=120000` — PASS, 1/1 deterministic rerun after each final visual update.
- `bash scripts/verify-fresh-install.sh` — final PASS: isolated production images built, migrations and initial boot completed, 4/4 E2E checks passed, persistent volumes were retained across a complete service restart, the same 4/4 checks passed after restart, and the isolated project/volumes were removed.

The fresh-install workflow had one non-reproducing intermediate post-restart
failure: after the destination H1 appeared, the platform scope selector was
temporarily empty. The retained diagnostics showed healthy Web/API/Postgres/
Redis services, successful workbench context/overview responses, and no 5xx,
timeout, or connection error. The immediately preceding full run and the final
clean rerun both passed 4/4 before and 4/4 after restart. No code or test was
changed to mask this event; the retained diagnostic directory is
`/var/folders/v5/x1cs0r0s197bgsbpmn1l8wnw0000gn/T/operations-ai-task7-diagnostics.gPeYDS`.

## Visual acceptance

The updated canonical baselines passed a no-update deterministic rerun. Original
resolution inspection included:

- `viewer-preflight-darwin.png`: read-only Viewer action and safe risk language.
- `preflight-darwin.png`: easy-mode status/evidence/version mappings without
  weakening the manual-review warning.
- `account-dashboard-error-darwin.png`: one H1, retained purpose, and explicit
  load failure while guidance is off.
- `settings-darwin.png`: easy-mode provider/retention/deletion-impact language.

## Boundary audit

- No API contract, database model, migration, dependency, permission predicate,
  business rule, storage key/default, URL/filter/form/draft/workflow behavior,
  secret handling, fixed disclaimer, isolation rule, or destructive confirmation
  ordering changed.
- Display preferences remain render-only and produce no business API request.
- No real external platform or paid model call was made.
- The pre-existing untracked `.superpowers/brainstorm/` directory was not
  modified or staged.

## Remaining acceptance concern

Independent Task 9B is still `independent_non_developer_pending`. This report
does not fabricate that evidence. Until a real independent participant completes
the session, `UX-COPY-01` and the overall feature must remain `partial`.
