# Final fix report: extension full-page capture and persistent devices

Date: 2026-08-11

## Outcome

All Critical/Important review findings and the listed Minor findings were addressed. The current branch is ready for re-review. No real creator platform, paid provider, user Chrome profile, user Compose project, or persistent user data was accessed or modified.

## Fixes completed

- Persistent-device lifecycle now distinguishes retryable infrastructure/network failure from terminal invalid/revoked identity. Retryable failures preserve the device key and registration; explicit online unlink revokes the device and all device tokens transactionally, while offline unlink discloses the possible server-side orphan.
- Public challenge issuance uses indistinguishable active/unknown/revoked response shapes and decoy cryptographic verification. Tests use injectable Redis namespaces and exact cleanup.
- Device API field names now disclose their real semantics: `device_description` and `last_session_issued_at`. OpenAPI JSON and generated TypeScript mirrors were regenerated.
- Same-route SPA mutation detection now includes route/query/filter/account anchors and a content-generation signal while allowing append-only lazy rows.
- Full-page capture removes the duplicate bottom observation, reports `bottom-unstable` and `overlap-unverified` as partial, uses one bounded stitch prefix, decodes sequentially, closes decoded bitmaps, and shares exact canonical PNG/base64 byte accounting with preview/image processing.
- Pairing key creation and popup submission are serialized. Full-page starts use generation fencing, exact `captureSessionId` binding, trusted arming senders, mutually exclusive arm state, and exact cleanup on response or thrown startup failures.
- Pre-0.3 capture payloads remain accepted only when all four metadata fields are absent, defaulting coherently to `visible / complete / visible / 1`; partially supplied metadata remains strictly rejected.
- Workbench guidance labels the OS shortcut as a default, explains browser customization/collision, and appears in pairing guidance for every role.
- Installation/privacy/validation/acceptance documents now describe 0.3.0 truthfully. Packaging and tests fail if the installation version/archive name drifts from the manifest.
- Accidental tracked root `task-6-report.md` and `task-7-report.md` were removed; required SDD evidence remains in the SDD directory.

## Verification evidence

- API: `1094 passed` with one upstream Starlette deprecation warning; Ruff and mypy passed.
- Extension: `16` files / `191` tests passed; TypeScript and ESLint passed.
- Web: `54` files / `330` tests passed; TypeScript, ESLint, and Next production build passed.
- Legacy Playwright regressions: `extension-safe-capture.spec.ts` and `full-loop.spec.ts` both passed (`2 passed`) against fresh task-owned tmpfs PostgreSQL, Redis, and MinIO containers on random loopback ports.
- Extension Playwright acceptance: `extension-pairing-safe-capture.spec.ts` passed (`1 passed`) with real unpacked extension Popup, Service Worker, content-script boundary, persistent key renewal, and explicit `captureVisibleTab` automation limitation. The final Playwright marker is `passed` with no failed tests.
- OpenAPI generation completed; `packages/shared-schemas/openapi.json` exactly matches `apps/api/openapi.json`, and `packages/shared-schemas/src/schema.ts` exactly matches `apps/web/src/generated/api.ts`.
- PostgreSQL migration tests passed inside the isolated pgvector container as part of the full API suite.
- Deterministic archive test passed across UTC and Asia/Shanghai. Final Chrome and Edge 0.3.0 ZIPs are byte-identical with SHA-256 `005b113e9f6226500fafc5b8019d54bef6a2aa8412e35708131acb8c180a8fdd`.
- Release artifact verification reported `release_artifact=clean`; repository secret scan reported `secret_scan=clean`; `git diff --check` passed.

## Isolation and cleanup

All task-owned PostgreSQL, Redis, MinIO, and extension-E2E containers were removed by exact validated names. Temporary schemas, browser profiles, marker files, and Playwright servers were removed by their scoped teardown. A final process/container check found no task-owned test servers or containers. Existing user Compose containers and volumes were left untouched.

## Remaining manual boundary

Real `captureVisibleTab` gesture acceptance in user macOS Chrome and real Douyin/Xiaohongshu compatibility remain `not_run`, exactly as documented. They require explicit user action/authorization and are not inferred from component or synthetic browser evidence.
