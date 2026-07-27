# Task 7 — Docker deployment, migration, and synthetic demo report

## Status

- Branch: `codex/backup-open-source`
- Commit: `chore: make fresh docker deployment reproducible` (the final local `HEAD` is the Task 7 handoff commit)
- Historical migrations: unchanged; current head remains `20260727_0027_operations_observability.py`.
- Remote operations: no pull, push, or origin modification performed.

## RED evidence

Before implementation, `apps/api/.venv/bin/python -m pytest apps/api/tests/test_compose_config.py apps/api/tests/demo/test_demo_seed.py -q` produced **3 failures / 8 passes**:

1. no `bucket-init` or opt-in `demo-seed` one-shot service existed;
2. API Dockerfile had only one `FROM` stage;
3. `app.demo_seed` did not exist.

After discovering that an interrupted profile run could leave an exited `demo-seed` container, a cleanup-contract test was added and deliberately failed because the trap did not include `--profile demo`. The trap now includes that profile. This was a script cleanup defect, not a user-volume operation.

## Implementation

- API and Web use multi-stage production images, locked to existing Python 3.12 and Node 22 base-image digests. The existing digests were retained; no unverified digest was invented for Postgres, Redis, or MinIO, whose explicit non-`latest` tags are retained.
- API runs Uvicorn as `appuser`; Worker reuses this image. Web runs Next standalone output as `nextjs`. Application files are owned by their non-root runtime users; API, Worker, and Web are read-only with only `/tmp` mounted writable, drop all capabilities, and set `no-new-privileges`.
- Compose has named PostgreSQL, Redis, and object-storage volumes; data-service ports bind to localhost by default. `migrate`, `bucket-init`, and profile-gated `demo-seed` are separate one-shot services. API and Worker wait for successful migration; Web waits for API readiness. Neither API nor Worker performs Alembic work.
- `bucket-init` idempotently creates the configured S3 bucket. Health checks use `/health/live` / `/health/ready` semantics, with API readiness checking PostgreSQL, Redis, and S3.
- `.env.example` documents purpose, local/production usage, and security handling for all deployment settings. Production rejects development database, S3, signing, and model-secret defaults. Mock mode remains keyless.
- `python -m app.demo_seed` requires explicit `DEMO_SEED_ENABLED=true`. It creates deterministic, synthetic AI-tech Demo records only, marks the workspace with `demo:synthetic-ai-tech-v1`, writes confirmed but analytics-ineligible snapshots, and writes one deterministic placeholder object. Re-running returns `already present` without touching non-demo workspaces, creating invitations, storing model keys, or emitting product events.
- The public Demo API now reads the seeded database records rather than an in-memory frontend/demo constant. OpenAPI and generated TypeScript include `seed_version`.
- `scripts/verify-fresh-install.sh` uses a unique validated Compose project, temporary environment file, random checked localhost ports, isolated named volumes, diagnostics, traps, normal `down` before restart, then profile-aware `down --volumes` only for its own project.

## Verification evidence

Passed:

- `bash -n scripts/verify-fresh-install.sh`
- `docker compose -f infra/docker/compose.yml config`
- `apps/api/.venv/bin/python -m pytest apps/api/tests/test_compose_config.py apps/api/tests/demo apps/api/tests/architecture/test_openapi.py apps/api/tests/models/test_secret_storage.py -q` — **32 passed**
- Task 7 focused green cycle before the OpenAPI/security additions — **15 passed**
- `apps/api/.venv/bin/python -m ruff check apps/api/app apps/api/tests` — clean
- `bash scripts/secret-scan.sh` — `secret_scan=clean`
- API production image build and inspection — `user=appuser`, Uvicorn production command
- Web production builder — Next production build passes, then Web Vitest **24 files / 49 tests passed**. `next typegen && tsc --noEmit` completed successfully in that builder.

Final independent acceptance ran the full API suite against a disposable tmpfs-backed pgvector container and completed with **636 passed / 0 failed**. The migration-focused suite passed **4 tests**; a genuinely empty database upgraded through head `20260727_0027_operations_observability.py`; `alembic check` reported no pending operations; and runtime schema consistency checks were clean. The temporary database existed only in container tmpfs, and no persistent or user database was connected, stamped, migrated, or modified. The final full Mypy command reports **Success: no issues found in 143 source files**.

## Fresh-install / persistence verification

The isolated verification completed successfully using project `operations_ai_task7_31987_31310`: real API/Web image builds, PostgreSQL/Redis/MinIO readiness, and all three independent one-shot jobs completed successfully. The first containerized Playwright run passed (**1 passed**), the project was stopped without removing volumes, and the second startup revalidated the seeded PostgreSQL records, MinIO object, Redis key, and a second containerized Playwright run (**1 passed**). The script exited 0 and removed its isolated project and volumes; the final independent fresh-install acceptance also exited 0.

The test script retains macOS-compatible `mktemp` templates and profile-aware cleanup. Interrupted earlier attempts retained only their diagnostics directories for inspection; no default Compose project or user volume was removed.

## Known limitations / follow-up

- The environment has no system-installed `node` binary; Web verification used the bundled locked Node runtime and the actual Docker builder.
- Task 8 remains out of scope: no README/LICENSE/contribution work, supply-chain CI, SBOM, vulnerability policy, or release documentation was added.

## Review remediation

The review found that the first database-backed Demo only exposed account/post summaries. A second RED→GREEN cycle added a real seeded public Demo closure: published content, confirmed snapshots, a persisted benchmark run, a Mock analysis and suggestion, style sample/profile, confirmed fact, private synthetic risk document/chunk, and a draft content record. All are queried by the Demo API, rendered by the public Demo page, have `synthetic`/Mock disclosure, and remain analytics-ineligible/read-only.

The same cycle added `SESSION_SIGNING_SECRET` to runtime settings and Compose with non-development default/length rejection; fixed failure diagnostics so failed fresh-install runs retain the safe diagnostics directory and print its path; and replaced the host `pnpm` E2E invocation with a profile-gated, explicitly versioned Playwright container. The Playwright image is pinned by explicit `v1.61.1-noble` tag; its registry digest was observed during local resolution but is not hard-coded because it was not present in the original deployment lock policy.

Review-remediation verification: `apps/api/.venv/bin/python -m pytest apps/api/tests/demo apps/api/tests/models/test_secret_storage.py apps/api/tests/test_compose_config.py apps/api/tests/architecture/test_openapi.py -q` — **37 passed**; Ruff, Compose config, shell syntax, diff checks, and the secret scan passed. The full containerized fresh-install flow is now executed successfully in this host, including both Playwright runs and restart-persistence assertions.

## Fresh-install execution remediation

An independent execution found two concrete runtime defects. Compose v5 treats an expected exit-0 profile one-shot as a failure when it is included in `up --wait`; the verifier now starts detached, obtains each of `migrate`, `bucket-init`, and `demo-seed` with `compose ps -a -q`, and checks each real exit code with `docker wait`. It then performs bounded, separate API readiness and Web health probes. The restart path uses the same sequence and performs a normal profile-aware `down` without removing volumes.

The Web standalone image had copied a monorepo standalone tree whose server lives at `/app/apps/web/server.js`, while its command targeted `/app/server.js`. Runtime COPY destinations now preserve the monorepo path and static directory, and the command is `node apps/web/server.js`. Verification includes contract RED→GREEN tests, a rebuilt image, an actual non-root container start, and a successful `GET /demo` smoke probe. The profile-gated E2E image is explicitly built before its first run so it cannot execute a stale cached test source; its closure-card test uses heading roles to avoid duplicate-title strict-mode ambiguity.

## Final acceptance remediation

Full Mypy acceptance exposed one variable-type collision in `demo_seed.py`: the loop-local `objective` model established a non-optional inferred type, while a later query reused the name for `ObjectiveProfile | None`. The later query now uses the semantically distinct `first_objective` and `first_benchmark_profile` names and retains explicit non-null assertions before constructing the draft. Verification passed with Mypy clean across **143 source files** and the Task 7 focused suite at **37 passed**.

The OpenAPI drift gate then exposed a stale generated TypeScript representation for `DemoWorkspaceRead`. The formal `pnpm schemas:generate` chain—Python OpenAPI export followed by locked `openapi-typescript` **7.10.1**—left `openapi.json` unchanged and regenerated only `packages/shared-schemas/src/schema.ts`. The generated diff expands the Demo dictionary fields to index signatures and restores generator-defined field ordering; no generated file was hand-edited. `pnpm schemas:check`, Web `next typegen && tsc --noEmit`, and Web Vitest (**24 files / 49 tests**) all passed.
