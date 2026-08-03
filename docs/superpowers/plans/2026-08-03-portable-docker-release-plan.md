# Cross-Platform Portable Docker Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Every behavior change uses superpowers:test-driven-development. Stop after each task commit and report its commit SHA and fresh verification evidence to the acceptance thread.

**Goal:** Produce one deterministic ZIP that lets Windows and macOS users with Docker Desktop start the complete operations platform, create a writable local workspace once, retain data across restarts, and later publish the same artifact through a governed GitHub Release.

**Architecture:** Keep the existing Docker Compose deployment as the only runtime. Add thin OS-specific wrappers, a tracked-files-only Python release builder, an isolated local-state boundary for first-run workspace credentials, and a tag-triggered release workflow. Do not add a second application stack or native desktop runtime.

**Tech Stack:** Docker Compose v2, Bash/macOS `.command`, Windows Batch + PowerShell, Python 3.12 standard library, pytest, existing `release-security.py`, GitHub Actions.

## Global Constraints

- The approved design is `docs/superpowers/specs/2026-08-03-portable-docker-release-design.md`.
- The current implementation base is commit `196ddf4` on branch `codex/workbench-redesign`.
- The package must not contain `.git`, `.env`, `.local-state`, database files/dumps, backups, logs, API keys, invite codes, cookies, tokens, `node_modules`, `.venv`, build caches, or `.superpowers/brainstorm`.
- Do not stage, modify, delete, archive, or include the pre-existing untracked `.superpowers/brainstorm/`.
- The default runtime remains `APP_MOCK_MODE=true`; do not call real Qianwen APIs or include any model key.
- Stop scripts must preserve Docker volumes. Do not create a double-click destructive reset command.
- Never terminate unrelated processes to resolve port conflicts.
- The ZIP contains both Windows and macOS entrypoints; Windows runtime compatibility remains `not_run` until a real Windows + Docker Desktop session is recorded.
- Mac runtime acceptance must use an unpacked artifact, a random test Compose project, random ports, `PORTABLE_NO_OPEN=1`, and cleanup only resources created by that test.
- Task 9B remains `partial`; do not claim independent non-developer acceptance.
- The existing out-of-scope Docker RiskRAG fixture-path P1 remains separately governed. Do not silently package repository test fixtures as production runtime data.
- Do not push, merge, publish a GitHub Release, or change repository visibility in the development task. The acceptance thread owns those external actions.

---

### Task 1: Portable launcher contracts and local-state boundary

**Files:**
- Create: `portable/启动运营工具-macOS.command`
- Create: `portable/停止运营工具-macOS.command`
- Create: `portable/启动运营工具-Windows.bat`
- Create: `portable/停止运营工具-Windows.bat`
- Create: `portable/使用说明.txt`
- Modify: `.gitignore`
- Modify: `scripts/release-security.py`
- Test: `apps/api/tests/open_source/test_portable_launchers.py`

**Interfaces:**
- Consumes: existing `infra/docker/compose.yml`, `.env.example`, `POST /v1/workspaces`, `/health/ready`, and `/enter`.
- Produces: four launcher files, `.local-state/bootstrap.json`, `.local-state/首次登录信息.txt`, and release allowlist support for `portable/**`.

- [ ] **Step 1: Read the test-writing rules**

Read `superpowers:test-driven-development/writing-good-tests.md` completely before adding tests.

- [ ] **Step 2: Write failing launcher contract tests**

Add real file-contract tests. The production change that makes them pass is the presence of safe launchers and the new ignore/allowlist rules.

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_portable_local_state_is_ignored_and_release_allowlisted() -> None:
    assert ".local-state/" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    security = (ROOT / "scripts/release-security.py").read_text(encoding="utf-8")
    assert 'r"portable/' in security


def test_stop_launchers_never_delete_volumes() -> None:
    for name in ("停止运营工具-macOS.command", "停止运营工具-Windows.bat"):
        text = (ROOT / "portable" / name).read_text(encoding="utf-8")
        assert " down" in text
        assert "--volumes" not in text
        assert "volume rm" not in text.lower()


def test_start_launchers_preserve_existing_environment_and_bootstrap() -> None:
    mac = (ROOT / "portable/启动运营工具-macOS.command").read_text(encoding="utf-8")
    windows = (ROOT / "portable/启动运营工具-Windows.bat").read_text(
        encoding="utf-8"
    )
    assert "cp -n .env.example .env" in mac
    assert "if not exist .env copy /Y .env.example .env" in windows
    for text in (mac, windows):
        assert ".local-state" in text
        assert "/v1/workspaces" in text
        assert "PORTABLE_NO_OPEN" in text
```

Also assert:

- Mac files start with `#!/usr/bin/env bash` and contain `set -Eeuo pipefail`.
- Windows files use `@echo off`, `setlocal`, `docker info`, and `docker compose version`.
- both launchers use default project name `operations-ai-local`;
- both accept environment overrides for project name, ports, and `PORTABLE_NO_OPEN`;
- both wait for API readiness and fail non-zero on timeout;
- both write bootstrap responses atomically through a temporary file and do not print an invite code in ordinary logs;
- both open `/enter`, not only `/demo`;
- documentation explicitly states Docker Desktop, 8 GB physical memory, 10 GB disk, first-run networking, default ports, Mock boundary, Windows `not_run`, and data backup rules.

- [ ] **Step 3: Run RED**

```bash
cd apps/api
.venv/bin/pytest tests/open_source/test_portable_launchers.py -q
```

Expected: FAIL because `portable/` and its launcher contracts do not exist.

- [ ] **Step 4: Implement the minimal macOS launchers**

The start script must derive the repository root from `BASH_SOURCE`, never from the caller's working directory.

Use these exact public environment names:

```bash
project_name="${PORTABLE_COMPOSE_PROJECT:-operations-ai-local}"
api_port="${API_PORT:-8000}"
web_port="${WEB_PORT:-3000}"
state_dir="$root_dir/.local-state"
bootstrap_file="$state_dir/bootstrap.json"
login_file="$state_dir/首次登录信息.txt"
```

The Compose wrapper must be:

```bash
compose() {
  docker compose \
    --project-name "$project_name" \
    --env-file "$root_dir/.env" \
    -f "$root_dir/infra/docker/compose.yml" \
    "$@"
}
```

Required behavior:

1. `docker info` and `docker compose version` must succeed.
2. `cp -n .env.example .env` creates but never overwrites local configuration.
3. Append no secrets to tracked files. Local defaults remain those already documented for development Mock mode.
4. Run `compose --profile demo up -d --build`.
5. Poll `http://127.0.0.1:${api_port}/health/ready` for at most 120 seconds with `curl --fail --silent`.
6. Poll `http://127.0.0.1:${web_port}/enter` for at most 60 seconds.
7. If `bootstrap.json` is absent, POST exactly `{"name":"本地运营工作区"}` to `/v1/workspaces`, write to `bootstrap.json.tmp`, validate that both `workspace_id` and `admin_code` are non-empty, then atomically rename.
8. Render `首次登录信息.txt` from the validated response with the `/enter` URL and invite code. Set `chmod 600` when supported. Copy only the invite code through `pbcopy` when available.
9. When `PORTABLE_NO_OPEN=1`, do not invoke `open`; otherwise run `open "http://127.0.0.1:${web_port}/enter"` and treat browser-open failure as a warning, not a service failure.
10. On bootstrap failure, keep the running platform and show the exact retry command; do not write an initialized marker.

Use macOS built-in `/usr/bin/plutil` to read the two JSON fields:

```bash
workspace_id="$(/usr/bin/plutil -extract workspace_id raw -o - "$bootstrap_tmp")"
admin_code="$(/usr/bin/plutil -extract admin_code raw -o - "$bootstrap_tmp")"
```

Do not require `jq`, host Python, Node.js, or Homebrew.

The stop script calls only:

```bash
docker compose \
  --project-name "${PORTABLE_COMPOSE_PROJECT:-operations-ai-local}" \
  --env-file "$root_dir/.env" \
  -f "$root_dir/infra/docker/compose.yml" \
  --profile demo down
```

- [ ] **Step 5: Implement the minimal Windows launchers**

The `.bat` start script must:

- use `%~dp0..` as the project root;
- use `where docker`, `docker info`, and `docker compose version`;
- use `if not exist .env copy /Y .env.example .env`;
- default `PORTABLE_COMPOSE_PROJECT`, `API_PORT`, and `WEB_PORT` only when absent;
- call `docker compose --project-name ... --env-file ... -f ... --profile demo up -d --build`;
- use bounded PowerShell `Invoke-WebRequest` health polling;
- use PowerShell `Invoke-RestMethod` for workspace creation and `ConvertTo-Json` for atomic UTF-8 `bootstrap.json`;
- validate `workspace_id` and `admin_code` before replacing the temporary file;
- write `首次登录信息.txt` without echoing the code to normal command output;
- copy the code with `Set-Clipboard`;
- use `start "" "http://127.0.0.1:%WEB_PORT%/enter"` unless `PORTABLE_NO_OPEN=1`;
- preserve volumes in the stop script.

Do not require system Python, Node.js, `jq`, Git, WSL, PowerShell 7, or administrator privileges. Windows PowerShell 5.1-compatible syntax is required.

- [ ] **Step 6: Add ignore, release, and user-documentation boundaries**

Add exactly:

```gitignore
.local-state/
```

Extend `SOURCE_ALLOWED_PATTERNS` with controlled text and launcher extensions under `portable/`:

```python
r"portable/[A-Za-z0-9._\-\u4e00-\u9fff]+\.(?:bat|command|txt)"
```

The Chinese usage guide must explain:

- start/stop instructions for both systems;
- first launch may take 5–15 minutes;
- data survives normal stop/restart;
- complete data removal is intentionally not a double-click action;
- move real data using product ZIP backup/restore;
- `.local-state/首次登录信息.txt` is sensitive;
- Mock is default and Qianwen keys are user-provided;
- Windows compatibility status remains unverified until real acceptance.

- [ ] **Step 7: Run GREEN and focused security regression**

```bash
cd apps/api
.venv/bin/pytest \
  tests/open_source/test_portable_launchers.py \
  tests/open_source/test_release_security.py -q
cd ../..
pnpm secret:scan
git diff --check
```

Expected: all PASS and `secret_scan=clean`.

- [ ] **Step 8: Commit Task 1**

```bash
git add \
  .gitignore \
  portable \
  scripts/release-security.py \
  apps/api/tests/open_source/test_portable_launchers.py
git commit -m "feat: add cross-platform portable launchers"
```

Stop and report the commit SHA, RED evidence, GREEN counts, exact changed files, and any platform-specific limitation.

---

### Task 2: Deterministic tracked-source release builder

**Files:**
- Create: `scripts/build-portable-release.py`
- Create: `scripts/release_policy.py`
- Create: `apps/api/tests/open_source/test_portable_builder.py`
- Modify: `scripts/release-security.py`
- Modify: `portable/使用说明.txt`

**Interfaces:**
- Consumes: Git `HEAD`, `SOURCE_ALLOWED_PATTERNS`, and the four launchers from Task 1.
- Produces: `PortableBuildResult`, `release-manifest.json`, `checksums.txt`, and `operations-ai-portable-<version>.zip`.

- [ ] **Step 1: Write failing builder tests**

Define the public Python interface in the tests:

```python
@dataclass(frozen=True)
class PortableBuildResult:
    zip_path: Path
    sha256: str
    file_count: int


def build_portable_release(
    *,
    repository: Path,
    output_dir: Path,
    version: str,
    source_date_epoch: int,
) -> PortableBuildResult:
    ...
```

Tests must use temporary Git repositories with committed fixtures, not mocks.

Cover:

- rejects an invalid semantic version outside `[0-9]+\.[0-9]+\.[0-9]+`;
- rejects tracked symlinks;
- refuses a dirty tracked worktree but ignores the protected untracked `.superpowers/brainstorm/`;
- includes only files returned by `git ls-files --cached`;
- rejects tracked `.env`, `.local-state`, database/dump/backup, private-key/certificate, oversized file, and non-allowlisted binary;
- copies Task 1 launchers to the ZIP root using the four Chinese entrypoint names;
- retains the executable bit for macOS `.command` entries;
- normalizes Windows entrypoints to CRLF and text files to UTF-8;
- fixes every ZIP timestamp from `SOURCE_DATE_EPOCH`;
- sorts archive entries byte-for-byte;
- produces the same ZIP SHA-256 twice from the same commit, version, and epoch;
- changes the hash when a committed source file changes;
- `release-manifest.json` records version, source commit, source epoch, path, size, mode, and SHA-256 for every payload file;
- `checksums.txt` includes the final ZIP SHA-256 outside the ZIP, while the internal manifest never self-hashes recursively.

- [ ] **Step 2: Run RED**

```bash
cd apps/api
.venv/bin/pytest tests/open_source/test_portable_builder.py -q
```

Expected: FAIL because `scripts/build-portable-release.py` does not exist.

- [ ] **Step 3: Implement tracked-tree collection and validation**

Use `subprocess.run(..., check=True, text=False)` with argument arrays. Do not invoke a shell.

Required helpers:

```python
def tracked_paths(repository: Path) -> tuple[str, ...]: ...
def validate_release_path(path: str) -> None: ...
def normalized_payload(repository: Path, path: str) -> bytes: ...
def build_manifest(entries: tuple[ManifestEntry, ...], *, version: str,
                   commit: str, source_date_epoch: int) -> bytes: ...
```

Resolve each path under the repository and fail closed when `resolved_path` escapes `repository.resolve()`. Reject symlinks before reading. Move `SOURCE_ALLOWED_PATTERNS` and `source_path_is_allowlisted(path: str) -> bool` into `scripts/release_policy.py`, then import the same function from both the builder and `release-security.py`. Do not retain a second allowlist or a compatibility copy.

Dirty-tree validation must use:

```bash
git status --porcelain=v1 --untracked-files=no
```

The pre-existing untracked brainstorm directory therefore remains irrelevant and untouched.

- [ ] **Step 4: Implement deterministic ZIP generation**

Use `zipfile.ZipFile` with `ZIP_DEFLATED`, fixed compression level, explicit `ZipInfo`, normalized `/` paths, and Unix modes:

```python
info.create_system = 3
info.external_attr = (mode & 0xFFFF) << 16
info.date_time = fixed_zip_datetime(source_date_epoch)
```

Reject source epochs before the ZIP minimum date. Map:

- `portable/启动运营工具-macOS.command` → `启动运营工具-macOS.command`
- `portable/停止运营工具-macOS.command` → `停止运营工具-macOS.command`
- `portable/启动运营工具-Windows.bat` → `启动运营工具-Windows.bat`
- `portable/停止运营工具-Windows.bat` → `停止运营工具-Windows.bat`
- `portable/使用说明.txt` → `使用说明.txt`

Keep the `portable/` source copies out of the final payload to avoid duplicate user entrypoints.

Write the ZIP to a temporary sibling path, fsync it, then atomically replace the final artifact. Write the same canonical `release-manifest.json` next to the ZIP and inside it. Write `checksums.txt` next to the ZIP.

- [ ] **Step 5: Extend release verification**

Add a `verify-portable-release` command to `release-security.py`:

```bash
python scripts/release-security.py verify-portable-release \
  --path dist/portable/operations-ai-portable-0.1.0.zip
```

It must independently reject:

- duplicate/case-colliding/Unicode-normalization-colliding paths;
- absolute paths and `..`;
- symlinks and encrypted entries;
- missing launchers, manifest, checksum contract, `.env.example`, Compose file, API and Web sources;
- any forbidden sensitive path;
- manifest hash or size mismatch;
- files not covered by the manifest;
- unexpected executable files.

- [ ] **Step 6: Run GREEN and reproducibility verification**

```bash
cd apps/api
.venv/bin/pytest \
  tests/open_source/test_portable_builder.py \
  tests/open_source/test_release_security.py -q
cd ../..
apps/api/.venv/bin/python scripts/build-portable-release.py \
  --repository . \
  --output-dir dist/portable \
  --version 0.1.0 \
  --source-date-epoch 1785744000
apps/api/.venv/bin/python scripts/release-security.py \
  verify-portable-release \
  --path dist/portable/operations-ai-portable-0.1.0.zip
pnpm secret:scan
git diff --check
```

Build twice and assert the printed ZIP SHA-256 is identical.

- [ ] **Step 7: Commit Task 2**

```bash
git add \
  scripts/build-portable-release.py \
  scripts/release_policy.py \
  scripts/release-security.py \
  apps/api/tests/open_source/test_portable_builder.py \
  portable/使用说明.txt
git commit -m "build: create deterministic portable release"
```

Do not commit `dist/portable/**`. Stop and report the commit SHA, file count, ZIP size, both hashes, tests, and release-verifier result.

---

### Task 3: Unpacked artifact fresh-install and writable-workspace acceptance

**Files:**
- Create: `scripts/verify-portable-release.sh`
- Create: `apps/api/tests/open_source/test_portable_acceptance_contract.py`
- Modify: `portable/启动运营工具-macOS.command`
- Modify: `portable/启动运营工具-Windows.bat`
- Modify: `portable/使用说明.txt`

**Interfaces:**
- Consumes: Task 2 ZIP, launcher environment overrides, existing Compose health checks, and `POST /v1/sessions/invite`.
- Produces: repeatable macOS artifact acceptance and a machine-readable `portable-acceptance.json`.

- [ ] **Step 1: Write failing acceptance-contract tests**

Tests must assert that `scripts/verify-portable-release.sh`:

- requires an explicit ZIP path;
- creates a random `operations_ai_portable_test_` Compose project;
- selects random loopback ports;
- sets `PORTABLE_NO_OPEN=1`;
- unpacks to `mktemp -d`;
- invokes the unpacked macOS launcher, never the repository launcher;
- verifies API readiness and Web `/enter`;
- reads `.local-state/bootstrap.json` without printing the invite code;
- redeems the generated invite through `/v1/sessions/invite`;
- creates one account/content fixture through official APIs;
- stops without volumes, restarts, and verifies the same workspace and fixture;
- runs the start launcher a second time and proves the workspace count did not increase;
- records Windows runtime as `not_run`, macOS runtime as `passed`, exact source commit, ZIP SHA-256, run time, and Docker versions;
- cleanup accepts only project names beginning `operations_ai_portable_test_`;
- always removes the test project's containers, networks, volumes, temporary unpack directory, and temporary state after evidence capture.

- [ ] **Step 2: Run RED**

```bash
cd apps/api
.venv/bin/pytest tests/open_source/test_portable_acceptance_contract.py -q
```

Expected: FAIL because the acceptance runner does not exist.

- [ ] **Step 3: Add explicit test overrides to both start launchers**

Launchers may consume but must never persist these optional variables:

```text
PORTABLE_COMPOSE_PROJECT
API_PORT
WEB_PORT
POSTGRES_PORT
S3_PORT
S3_CONSOLE_PORT
NEXT_PUBLIC_API_URL
WEB_ORIGIN
PORTABLE_NO_OPEN
```

User defaults remain unchanged. Test overrides are passed through Compose environment only. The launchers must not read arbitrary environment names into `.env`.

- [ ] **Step 4: Implement the isolated artifact verifier**

Follow the proven cleanup and readiness patterns in `scripts/verify-fresh-install.sh`, but use prefix `operations_ai_portable_test_` and the unpacked launcher.

The verifier must:

1. check Docker before creating resources;
2. build Task 2 artifact when `--build` is supplied, otherwise require the exact ZIP;
3. calculate ZIP SHA-256 before extraction;
4. extract with Python `zipfile` only after `verify-portable-release` succeeds;
5. execute the unpacked Mac launcher with random ports and `PORTABLE_NO_OPEN=1`;
6. validate one-shot `migrate`, `bucket-init`, and `demo-seed` exit codes;
7. redeem the local admin code without printing it;
8. create a minimal official account and content fixture;
9. record IDs only in the temporary evidence file;
10. stop, restart, and verify persistence;
11. rerun the start launcher and verify no duplicate local workspace;
12. write `portable-acceptance.json` with no code, cookie, CSRF token, title, body, prompt, or user data;
13. clean only test resources in the EXIT trap.

- [ ] **Step 5: Run contract GREEN**

```bash
cd apps/api
.venv/bin/pytest tests/open_source/test_portable_acceptance_contract.py -q
cd ../..
git diff --check
```

Expected: PASS.

- [ ] **Step 6: Run real macOS unpacked acceptance**

```bash
bash scripts/verify-portable-release.sh \
  --build \
  --version 0.1.0 \
  --source-date-epoch 1785744000
```

Expected:

- macOS `passed`;
- Windows `not_run`;
- local workspace created once;
- official invite login succeeds;
- fixture survives normal stop/restart;
- test Compose resources and temporary directories are absent afterward;
- no real provider call or real platform access.

- [ ] **Step 7: Run regressions**

```bash
cd apps/api
.venv/bin/pytest tests/open_source -q
cd ../..
pnpm --filter web test:run
pnpm --filter extension test
pnpm secret:scan
git diff --check
```

- [ ] **Step 8: Commit Task 3**

```bash
git add \
  portable \
  scripts/verify-portable-release.sh \
  apps/api/tests/open_source/test_portable_acceptance_contract.py
git commit -m "test: verify unpacked portable deployment"
```

Stop and report the commit SHA, artifact SHA-256, macOS acceptance result, persistence evidence, cleanup evidence, and honest Windows status.

---

### Task 4: GitHub Release automation and operator documentation

**Files:**
- Create: `.github/workflows/portable-release.yml`
- Create: `docs/open-source/portable-release.md`
- Modify: `README.md`
- Modify: `docs/open-source/release-checklist.md`
- Modify: `docs/open-source/supply-chain-security.md`
- Modify: `scripts/release-security.py`
- Test: `apps/api/tests/open_source/test_portable_workflow.py`

**Interfaces:**
- Consumes: Task 2 builder/verifier and Task 3 acceptance evidence schema.
- Produces: tag-triggered private/public Release automation with minimum permissions and accurate documentation.

- [ ] **Step 1: Write failing workflow-policy tests**

Parse the YAML with `yaml.safe_load` and assert:

- only tag glob `v*.*.*` triggers, and the first build step rejects any `GITHUB_REF_NAME` that does not fully match `v[0-9]+\.[0-9]+\.[0-9]+`;
- workflow-level `permissions: {contents: read}`;
- build job has no write permission and uploads the ZIP, checksum, manifest, and SBOM as an Actions artifact;
- publish job alone has `contents: write`;
- publish job depends on build and downloads the exact named artifact;
- every `uses:` action is pinned to a full 40-character commit SHA;
- no `pull_request_target`, `workflow_run`, self-hosted runner, external curl-pipe-shell, secret echo, or arbitrary third-party upload action exists;
- builder source epoch comes from the tagged commit timestamp;
- `gh release create` uses `--verify-tag`, the four governed assets, and `GH_TOKEN: ${{ github.token }}`;
- release notes state Windows runtime `not_run` unless an approved Windows acceptance artifact is present;
- docs never describe Docker as optional or claim a fully native application.

- [ ] **Step 2: Run RED**

```bash
cd apps/api
.venv/bin/pytest tests/open_source/test_portable_workflow.py -q
```

Expected: FAIL because the workflow and portable-release documentation do not exist.

- [ ] **Step 3: Implement the minimum-permission workflow**

The workflow stages are:

1. checkout with full tag history;
2. install pinned Python/uv only;
3. sync the locked API dev environment;
4. run portable builder tests and release-security tests;
5. build the ZIP using `version=${GITHUB_REF_NAME#v}` and the tagged commit epoch;
6. independently verify the ZIP;
7. generate the existing SPDX source SBOM;
8. run current-tree and history secret scans;
9. upload governed artifacts with pinned `actions/upload-artifact`;
10. in a separate write-permission job, download the artifact and run `gh release create`.

Do not publish Docker images in this task. Do not use a floating action tag.

- [ ] **Step 4: Document user and maintainer flows**

`docs/open-source/portable-release.md` must cover:

- Windows and macOS start/stop;
- Docker Desktop prerequisite and resource estimates;
- local writable-workspace bootstrap;
- `.local-state` sensitivity;
- normal persistence and product ZIP backup/restore;
- how maintainers build and verify the artifact locally;
- tag format and Release contents;
- current validation matrix;
- known real-provider, real-platform, Windows, Intel Mac, Task 9B, and RiskRAG limitations.

README quick start links to the portable guide without replacing the existing source Docker Compose instructions.

- [ ] **Step 5: Run GREEN and CI contract checks**

```bash
cd apps/api
.venv/bin/pytest \
  tests/open_source/test_portable_workflow.py \
  tests/open_source/test_release_security.py \
  tests/open_source/test_portable_builder.py -q
cd ../..
apps/api/.venv/bin/python scripts/release-security.py \
  verify-ci --path .github/workflows/ci.yml
pnpm secret:scan
git diff --check
```

Run the YAML workflow parser twice and confirm no generated drift.

- [ ] **Step 6: Commit Task 4**

```bash
git add \
  .github/workflows/portable-release.yml \
  README.md \
  docs/open-source/portable-release.md \
  docs/open-source/release-checklist.md \
  docs/open-source/supply-chain-security.md \
  scripts/release-security.py \
  apps/api/tests/open_source/test_portable_workflow.py
git commit -m "ci: publish governed portable releases"
```

Stop and report the commit SHA, workflow permissions, test results, and explicit non-publication confirmation.

---

### Task 5: Final portable artifact, full regression, and handoff

**Files:**
- Create locally only: `dist/portable/operations-ai-portable-0.1.0.zip`
- Create locally only: `dist/portable/checksums.txt`
- Create locally only: `dist/portable/portable-acceptance.json`
- Modify: `docs/acceptance/requirements-traceability.md`
- Create: `docs/acceptance/evidence/portable-release-2026-08-03.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: final local artifact and acceptance evidence for the independent acceptance thread.

- [ ] **Step 1: Build from a clean tracked tree**

Verify:

```bash
git status --porcelain=v1 --untracked-files=no
```

Expected: empty. The protected untracked brainstorm directory may remain visible only when untracked files are requested.

Build:

```bash
apps/api/.venv/bin/python scripts/build-portable-release.py \
  --repository . \
  --output-dir dist/portable \
  --version 0.1.0 \
  --source-date-epoch 1785744000
```

- [ ] **Step 2: Verify and inspect the final ZIP**

```bash
apps/api/.venv/bin/python scripts/release-security.py \
  verify-portable-release \
  --path dist/portable/operations-ai-portable-0.1.0.zip
unzip -l dist/portable/operations-ai-portable-0.1.0.zip
```

Manually inspect the bounded file listing for all five user-facing root files and the absence of forbidden paths. Do not print file bodies containing local bootstrap state.

- [ ] **Step 3: Run complete regression**

Use a disposable PostgreSQL dependency where required. Run fresh:

```bash
cd apps/api
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy app
cd ../..
pnpm --filter web test:run
pnpm --filter web lint
pnpm --filter web typecheck
pnpm --filter web build
pnpm --filter extension test
pnpm --filter extension lint
pnpm --filter extension typecheck
pnpm --filter extension build
pnpm schemas:check
pnpm metrics:check
pnpm secret:scan
git diff --check
```

Do not downgrade a failed check to a warning. Environment-dependent PostgreSQL tests must be rerun against an isolated temporary PostgreSQL and that resource must be removed.

- [ ] **Step 4: Run final unpacked macOS acceptance**

```bash
bash scripts/verify-portable-release.sh \
  --zip dist/portable/operations-ai-portable-0.1.0.zip
```

Expected: macOS passed, Windows not_run, no resources remain.

- [ ] **Step 5: Update traceability and evidence**

The evidence document records:

- source commit;
- ZIP name, size, file count, SHA-256;
- API/Web/Extension/static results;
- macOS fresh-install, login, persistence, idempotency, stop, restart, and cleanup;
- Windows `not_run`;
- no real provider/platform/data use;
- Task 9B still partial;
- out-of-scope Docker RiskRAG P1 still open;
- GitHub repository/release not modified by the development task.

Never record an invite code, session cookie, CSRF token, environment secret, title, body, Prompt, OCR text, or user data.

- [ ] **Step 6: Commit acceptance documents**

```bash
git add \
  docs/acceptance/requirements-traceability.md \
  docs/acceptance/evidence/portable-release-2026-08-03.md
git commit -m "docs: record portable release acceptance"
```

Do not commit `dist/portable/**`.

- [ ] **Step 7: Final independent review package**

Generate a review package for the acceptance thread:

```bash
git diff --binary 196ddf4..HEAD > \
  /tmp/portable-release-196ddf4..HEAD.diff
```

Report:

- all five task commit SHAs;
- final HEAD and clean tracked-tree status;
- exact ZIP absolute path, size, file count, and SHA-256;
- all test/build counts;
- macOS runtime acceptance evidence;
- honest Windows `not_run`;
- cleanup evidence;
- no push/merge/release/visibility change;
- protected brainstorm directory untouched.

Then pause. The acceptance thread performs code review, reruns high-risk checks, inspects the ZIP, decides whether the artifact is accepted, and owns any GitHub upload.
