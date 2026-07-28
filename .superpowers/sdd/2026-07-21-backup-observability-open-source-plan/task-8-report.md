# Task 8 — Open-source documentation, license, and supply-chain security report

## Status

`COMPLETE_WITH_RELEASE_BLOCKERS` — Task 8 implementation and its required local verification gates pass. Public release remains blocked by the items listed below; passing Task 8 is not approval to distribute a public release. Task 9 was not started. No pull, push, force-push, or origin modification was performed.

- Branch at start/end: `codex/backup-open-source`
- Start HEAD: `5d2a1856a3eadfe6880b4e3b0a70aad8d75af8eb`
- Database handling: no persistent developer database was connected, stamped, migrated, rebuilt, or deleted. Database and fresh-install checks used uniquely named isolated tmpfs/Compose environments with synthetic data; their containers, networks, volumes, schemas, temporary files, and object prefixes were removed.

## Changes

- Added root README, Apache-2.0 LICENSE, CONTRIBUTING, Contributor Covenant 2.1-derived Code of Conduct, SECURITY policy, current synthetic Demo PNG, architecture documents, deployment/backup/risk-governance documents, license/asset/supply-chain/release documents, security-exception registry, and this report.
- Added `scripts/release-security.py` and behavior tests for CI policy, source/extension allowlists, source SBOM scope, exception records, documentation commands, and Demo screenshot failure markers. `scripts/secret-scan.sh` now checks the current tracked and untracked tree plus all reachable history without echoing matches.
- Reworked CI for explicit read-only permission, SHA-pinned Actions, full checkout before history scan, source-release verification, audit/SBOM/image scan gates, extension archive checks, artifact upload, and isolated fresh-install execution.

## License and asset decision

Original source and documentation use Apache-2.0. The decision and direct runtime dependency/container/asset boundaries are documented in `docs/open-source/license-decision.md`; container images and dependencies retain their own terms. Direct Python, Web/Node, extension, and container scopes are enumerated there. Demo seed data, fixtures, README screenshot, and Demo content are synthetic; unlicensed platform rules, third-party article text, real user data, credentials, and private knowledge are excluded.

## RED → GREEN evidence

1. Initial focused suite: `apps/api/.venv/bin/python -m pytest apps/api/tests/open_source/test_release_security.py -q` produced **5 failures**: the release-security entry point was absent, history scanning only checked the current tree, and the required validators/SBOM generator did not exist.
2. After the minimum tooling implementation, the same suite passed **5 tests**.
3. Review-driven RED added full-checkout, source release, exception, non-image SBOM, untracked secret, nested artifact, README compose, and screenshot contracts. The focused suite showed expected failures for missing `fetch-depth: 0`, fake image SBOM output, missing validators, missing screenshot guard, and incorrect clean-history handling.
4. Final focused GREEN: `PYTHONDONTWRITEBYTECODE=1 apps/api/.venv/bin/python -m pytest apps/api/tests/open_source/test_release_security.py -q` — **14 passed**. The only warning is pytest cache write denial caused by this sandbox; test assertions and exit status passed.

## Focused verification actually run

- `python3 scripts/release-security.py verify-docs --root . --readme README.md --require-compose-config` — `docs_contract=clean`; this executed the README Compose config command.
- `python3 scripts/release-security.py verify-ci --path .github/workflows/ci.yml` — `ci_policy=clean` (read-only permissions, immutable Action SHAs, and `fetch-depth: 0`).
- `bash scripts/secret-scan.sh` and `bash scripts/secret-scan.sh --history` — both `secret_scan=clean`.
- `python3 scripts/release-security.py generate-sbom --output <tmp>` plus JSON parsing — API/Web source SPDX documents generated and parsed. The source tool deliberately does **not** claim image coverage.
- `python3 scripts/release-security.py verify-exceptions --path .github/security-exceptions.yml` — `security_exceptions=clean`.
- Source staging built from tracked plus untracked release candidates — `source_release=clean`.
- Existing Chrome and Edge ZIP artifacts were independently unzipped into temporary directories; both passed `verify-artifact` allowlist/dynamic-code/secret checks.
- `docker compose -f infra/docker/compose.yml config --quiet` and `git diff --check` — exit 0.
- A unique isolated Mock Compose project was built with synthetic seed data and internal API/CORS routing; the repository E2E image captured `/demo` after waiting. The resulting `docs/assets/public-demo-synthetic-v1.png` was visually checked and shows the current synthetic AI-tech Demo, not an error page. The project and its volumes were then removed.

## CI and release policy

CI has top-level `contents: read`, no declared secrets, full history checkout, SHA-pinned checkout/pnpm/setup-node/setup-uv/upload-artifact Actions, current-tree/history scan, ecosystem-specific production audit, source/API/Web SPDX generation, Syft image SBOM output/parse, Trivy API/Web Critical/High block, source/extension allowlists, and a fresh-install script step. SBOMs are uploaded as artifacts. `.github/security-exceptions.yml` is an explicit empty list; documented exceptions require CVE, affected version, impact, mitigation, owner and review date, but do not silently bypass image gates.

## Known limitations and release blockers

- A real security reporting email/channel is not configured; `SECURITY.md` calls this a release blocker.
- Compose deployment dependencies pgvector、Redis、MinIO remain tag-only and were not included in the successful API/Web Trivy claims. A complete Compose release must pin reviewed digests and scan all three images first.
- Redis/MinIO redistribution and license-obligation decisions remain open. Until resolved, they are user-pulled deployment dependencies and are excluded from the project's image distribution set.
- This does not provide real platform-page, Windows/Edge, real-model, production-capacity, non-developer, or Task 9 acceptance evidence.
- Vulnerability databases and dependency metadata are point-in-time inputs. The pinned CI gates must be rerun for each release.

## Final verification (2026-07-28)

The main agent independently completed the handoff gates:

- Task 8 focused suite: **39/39**.
- API full suite: **675/675** against an automatically removed tmpfs PostgreSQL instance.
- Web: **49/49**; Extension: **38/38**; Ruff, Mypy (**143 source files**), ESLint, TypeScript and production Web build all passed.
- OpenAPI and platform-metrics drift checks passed. Empty isolated schema migrated to `20260727_0027`; Alembic check and schema consistency passed.
- Node production audit and Python production audit both reported no known vulnerabilities after the pinned Next/Sharp/PostCSS and cryptography remediations.
- Source release allowlist, source SPDX generation and official `spdx-tools==0.8.3` validation passed.
- API and Web images built successfully. Syft `v1.44.0` final-image SPDX documents passed the official validator; Trivy `0.69.3` reported **0 Critical / 0 High** for both images.
- Current-tree scan, full-history project scan and fixed-digest Gitleaks `v8.28.0` scan passed. `.gitleaksignore` contains only six exact historical synthetic-fixture fingerprints, not wildcard/path exclusions.
- Fresh-install verification used a unique isolated Compose project, passed the synthetic E2E before and after restart (**1/1** each), and was cleaned up.
- Chrome and Edge extension packages used the same business source and produced the same final SHA-256 `9d67f7ad0d92e75a9876ac09682f7e0c0ce041f49a02147e762aeb3234d7ce2a`.

## Review repair round 1

This section corrects the earlier report rather than silently preserving stale claims.

- **Correction — `.DS_Store`:** the earlier text said `docs/.DS_Store` was tracked and removed. A later index check showed it was not tracked and is absent from the working tree; that earlier “tracked removal” claim was false. The source-release verifier nevertheless rejects `.DS_Store` recursively.
- Secret scanning now includes ignored `.env*`, lockfiles and untracked files, with provider/token patterns for AWS, Google, GitHub, GitLab, Slack, npm, PyPI, Cookie and Authorization values. It emits only `secret_scan=clean|failed`; no matching value is printed. CI adds redacted Gitleaks `v8.28.0` pinned to `sha256:cdbb7c955abce02001a9f6c9f602fb195b7fadc1e812065883f695d1eeaba854`.
- Source-release policy now rejects recursive `.env*` (except `.env.example`), SQL/dump/backup/DB/key/cert/private material and symlinks. The asset inventory now names every tracked PNG/XLSX/Base64 fixture and records removal of the five unused default Next SVG files.
- API/Web source SBOMs now enumerate locked transitive packages, use unique SPDX package identifiers and document relationships. They are intentionally **source-lockfile** SBOMs only; Syft generates the distinct final-image SBOMs. CI validates every SBOM with `uvx --from spdx-tools==0.8.3 pyspdxtools -i`, not merely JSON parsing. Syft `v1.44.0` and Trivy `0.69.3` use immutable digests; the E2E Playwright `v1.61.1-noble` base is also digest-pinned. Syft `v1.18.1` was rejected during final verification because its npm `downloadLocation` values failed the official SPDX validator; the fixed-digest `v1.44.0` output for both final images passed `spdx-tools==0.8.3`.
- Extension packaging now writes a standard production-runtime SPDX document and a release manifest that lists every archive file and hashes each non-self file. The self entry uses a documented null hash because recursively hashing the manifest itself is impossible. CI validates Chrome/Edge SBOMs and manifests after rebuilding them.
- The Code of Conduct now contains the complete Contributor Covenant 2.1 pledge, standards, scope, reporting, enforcement responsibilities and four-level enforcement ladder. Documentation checks now recurse through all Markdown local links and structurally decode referenced PNG chunks/CRCs; CI invokes the Demo screenshot check explicitly. Exceptions reject unknown, empty, invalid and expired fields.

### Repair RED → GREEN evidence

1. Before the repair implementation, the focused behavior suite contained five review tests that failed for ignored dotenv/lockfile credentials, nested source-release sensitive files, missing transitive SBOM coverage, malformed exceptions, and incomplete extension manifest coverage (**14 passed, 5 failed**).
2. A second RED addition failed for source symlinks, non-README broken links/invalid PNG framing, and the absent SPDX structural command (**19 passed, 3 failed**).
3. Focused GREEN after the minimal repairs: `PYTHONDONTWRITEBYTECODE=1 apps/api/.venv/bin/python -m pytest apps/api/tests/open_source/test_release_security.py -q` — **22 passed**. The only warning is the sandbox denying pytest cache writes; assertions passed.
4. Focused commands that passed: recursive `verify-docs --require-compose-config`; `verify-demo-screenshot`; `verify-ci`; `verify-exceptions`; current and history `secret-scan`; source staging `verify-source-release`; generated API/Web `verify-sbom`; and `git diff --check`.
5. The official validator was actually run in a temporary, read-only mounted Python 3.12 container: `pip install spdx-tools==0.8.3 && pyspdxtools -i /sbom/api.spdx.json && pyspdxtools -i /sbom/web.spdx.json` exited 0. Local `uvx` is unavailable in this desktop runtime, so CI retains the fixed `uvx` form.

### Extension rebuild evidence

The initial shell PATH lacked Node, but the bundled Node runtime resolved that environmental limitation. With the provided runtime PATH, `pnpm --filter extension package:chrome` rebuilt both Chrome and Edge archives. Both archives were extracted to temporary directories and passed `verify-artifact` (including every-file release-manifest hashes) and `verify-sbom`. The same fixed `spdx-tools==0.8.3` temporary-container command parsed both extension SPDX documents with `pyspdxtools -i` and exited 0. This is focused package verification only; it does not claim full extension lint/typecheck/test coverage.

## Review repair round 2

### RED → GREEN evidence

1. Added eight isolated behavior tests for: ignored uppercase `COOKIE`/`AUTHORIZATION` dotenv values, historical whole-file scanner blind spots, unreviewed `docs/customer-data.json` and `apps/api/prod_snapshot.json`, a missing extension release manifest, YAML null/list/mapping exception values, missing screenshot provenance, mutable Node/uv versions, and monorepo-wide Web SBOM leakage. The focused RED run was **22 passed, 8 failed**.
2. Minimum repair implementation produced **30 passed** in `PYTHONDONTWRITEBYTECODE=1 apps/api/.venv/bin/python -m pytest apps/api/tests/open_source/test_release_security.py -q`; the sole warning is sandbox denial of pytest cache writes.
3. Follow-up focused policy checks passed: docs/provenance, Demo PNG, CI, strict exception registry, current/history secret scan, an allowlisted source staging directory, and `git diff --check`.

### Repair details

- `secret-scan.sh` now matches case-insensitive Cookie/Authorization spellings in ignored dotenv files and uses four documented **path-and-line** synthetic fixture exceptions instead of excluding entire files. Lockfiles remain in scope; scan status never prints matching content.
- Source release verification is now a recursive, auditable regular-expression allowlist for each release subtree, rather than a broad top-level allowlist plus denylist. It therefore rejects unreviewed JSON/data paths by default while retaining reviewed code, tests, assets and configuration paths.
- Extension verification now fails closed when `release-manifest.json` is absent.
- Exceptions are parsed with the already locked PyYAML `6.0.3` safe loader and a strict mapping/list/scalar schema. No lockfile changed: PyYAML was already present in the frozen API development group; CI invokes this tool through `uv run --project apps/api` so that locked dependency is used. Unknown keys, YAML null/collections/mappings, empty values, invalid format and expired dates fail.
- The public synthetic Demo PNG now has a checked-in SHA-256 provenance record naming the isolated Compose mock `/demo` capture and its Playwright source test. CI renders the synthetic Demo with Playwright, asserts visible UI evidence, and uploads the rendered audit screenshot. This is explicitly not a real-platform claim.
- CI pins Node `22.12.0` and uv `0.11.29`. The Web SBOM follows `apps/web` production edges, the production edge of its shared workspace package, and runtime optional dependencies; extension/E2E/development-only entries remain excluded, while target-platform runtime packages are included.
- `deployment.md` and `release-checklist.md` now state the fixed Playwright digest and make clear that exceptions are records, not vulnerability-gate bypasses.

## Review repair round 3

### RED → GREEN evidence

1. Added five focused tests for ignored dotenv `sk-proj-`/`sk-ant-` tokens, a changed secret at an allowlisted fixture line, directory symlinks, bare CI `python3` release-security execution, and Next runtime optional dependencies. The RED run was **30 passed, 5 failed**.
2. Focused GREEN before the exact Gitleaks-baseline regression was added: `PYTHONDONTWRITEBYTECODE=1 apps/api/.venv/bin/python -m pytest apps/api/tests/open_source/test_release_security.py -q` — **35 passed**. The final suite is **36 passed**. The only warning is the existing sandbox pytest-cache denial.
3. Also passed: current/history secret scan, `verify-ci`, source SBOM generation, and `git diff --check`. No full suite or E2E run was claimed.

### Repair details

- Secret detection now covers hyphenated modern provider prefixes `sk-proj-` and `sk-ant-`, including ignored dotenv files. Each synthetic scanner exception is now keyed by path, line and SHA-256 fingerprint of the exact matching synthetic line; changing the value at that line fails closed. Neither matches nor fingerprints expose secret values in scanner output.
- Source verification checks `Path.is_symlink()` before `Path.is_dir()`, so a directory symlink cannot bypass the recursive release allowlist.
- Every CI `release-security.py` invocation, including source release, SBOM and extension artifact checks, uses `uv run --project apps/api python`; `verify-ci` rejects a bare invocation. This ensures the locked PyYAML parser environment is used consistently.
- The Web SBOM graph now follows runtime `optionalDependencies` as well as normal production dependencies. It includes `sharp` and all resolved target-platform `@next/swc-*` packages while explicitly excluding Next's optional `@playwright/test` harness and importer-level E2E/dev dependencies.

## Final production dependency audit remediation

The main-agent verification on 2026-07-28 found release-blocking production advisories rather than suppressing them:

- The initial `pnpm audit --prod --audit-level high` reported Next.js `16.2.10`, Sharp `0.34.5`, and Next's PostCSS `8.4.31` path. Next was upgraded to `16.2.11`; pnpm workspace overrides force Sharp `0.35.0` and PostCSS `8.5.20`, the first patched versions accepted by the audit. The repeated production audit reports **No known vulnerabilities found**.
- The fixed `pip-audit==2.9.0` scan of the frozen API environment reported `cryptography 46.0.7` as affected by `GHSA-537c-gmf6-5ccf`; the direct constraint and lock were advanced to `cryptography 48.0.1`. A fresh Python 3.12 / uv `0.11.29` environment resolved exactly `48.0.1`, and the final local API environment was synchronized to that version before the full test run.
- The Sharp/PostCSS overrides are narrowly scoped supply-chain remediations because Next `16.2.11` still resolves vulnerable optional/runtime versions. They remain visible in `pnpm-workspace.yaml`, the lockfile and generated Web SBOM, and must be removed or revised when an upstream Next release carries patched constraints.

Compatibility evidence after these changes: Web tests **49/49**, Extension tests **38/38**, Task 8 focused tests **39/39**, Web production build, ESLint, TypeScript, Ruff and Mypy passed. API full pytest passed **675/675** with cryptography `48.0.1` against an automatically removed tmpfs PostgreSQL instance; empty-schema migration to `20260727_0027`, Alembic check and schema consistency also passed.

## Final review repair

- New binary test fixtures no longer pass the source-release allowlist by extension alone. Only the five PNG/XLSX/Base64 fixtures individually recorded in `third-party-assets.md` are allowlisted; a synthetic unreviewed `customer-export.xlsx` produced the expected RED failure before the file-level allowlist repair.
- The release report and checklist no longer describe the security contact as the only blocker. They explicitly separate the scanned project-built API/Web images from the tag-only pgvector、Redis、MinIO deployment dependencies and record the unresolved Redis/MinIO distribution-license decision.
