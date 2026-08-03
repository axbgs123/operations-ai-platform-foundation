# Owner Workspace Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow each team's first manager to create a private workspace and become its initial administrator without an invite code, while preserving one-person invite codes for every later member.

**Architecture:** Add a dedicated atomic owner-onboarding service and API that creates the Workspace, Admin member and authenticated session in one transaction. Expose it as a second `/enter` path, remove launcher-owned workspace bootstrap, then rebuild and revalidate the deterministic portable artifact before returning to portable-release Task 3.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, Next.js/React, Vitest/Testing Library, Python release tooling, Bash, Windows Batch, OpenAPI-generated TypeScript.

## Global Constraints

- The approved design is `docs/superpowers/specs/2026-08-03-owner-workspace-onboarding-design.md`.
- “No invite code” applies only while creating a new Workspace and its first Admin member.
- A display name is never an authentication credential.
- Joining an existing Workspace continues to require an independently issued invite code.
- Workspace, member, session and audit creation must succeed or roll back together.
- The new endpoint must never return an invite code, session token, cookie value or internal exception.
- Existing `POST /v1/workspaces` remains compatible during this closeout; new product UI and portable launchers must not call it.
- Keep the existing configured Web-origin CORS boundary; local Web and API ports are intentionally different, so do not add a literal same-origin rejection.
- Demo remains isolated from private workspaces.
- Do not add passwords, email, phone, third-party login, team discovery or reusable team-wide codes.
- Do not add dependencies or database migrations.
- Preserve the existing untracked `.superpowers/brainstorm/` directory exactly as-is; never read, modify, stage, commit, scan or package it.
- Do not push, merge, publish a Release, change repository visibility, call real providers/platforms or touch the original persistent database/volumes.

---

### Task 1: Atomic owner onboarding API

**Files:**
- Modify: `apps/api/app/modules/workspace/schemas.py`
- Modify: `apps/api/app/modules/workspace/auth.py`
- Modify: `apps/api/app/modules/workspace/router.py`
- Modify: `apps/api/app/core/rate_limit.py`
- Create: `apps/api/tests/workspace/test_owner_onboarding.py`
- Modify: `apps/api/tests/core/test_rate_limit.py`
- Modify generated: `packages/shared-schemas/openapi.json`
- Modify generated: `packages/shared-schemas/src/schema.ts`

**Interfaces:**
- Consumes: existing `Workspace`, `WorkspaceMember`, `WorkspaceSession`, `AuditLog`, cookie configuration and `SessionCreated`.
- Produces: `WorkspaceOwnerOnboard`, `InviteAuthService.create_owner_session(workspace_name: str, display_name: str) -> AuthenticatedSession`, and `POST /v1/workspaces/onboard`.

- [ ] **Step 1: Read implementation rules and current contracts**

Read completely:

```text
/Users/baiyan1/.codex/plugins/cache/superpowers-dev/superpowers/6.2.0/skills/test-driven-development/SKILL.md
apps/api/app/modules/workspace/schemas.py
apps/api/app/modules/workspace/auth.py
apps/api/app/modules/workspace/router.py
apps/api/app/core/rate_limit.py
apps/api/tests/workspace/test_workspace_api.py
apps/api/tests/workspace/test_invites.py
apps/api/tests/core/test_rate_limit.py
```

Do not edit implementation before the failing tests exist.

- [ ] **Step 2: Write failing API and service tests**

Create `apps/api/tests/workspace/test_owner_onboarding.py` using the existing isolated SQLite/TestClient pattern. Cover these exact outcomes:

```python
def test_owner_onboarding_creates_admin_session_without_invite(client):
    response = client.post(
        "/v1/workspaces/onboard",
        json={"workspace_name": "C哥内容团队", "display_name": "小白"},
    )
    assert response.status_code == 201
    assert set(response.json()) == {"workspace_id", "member_id", "csrf_token"}
    assert response.cookies.get("session")


def test_owner_onboarding_response_never_contains_credentials(client):
    payload = client.post(
        "/v1/workspaces/onboard",
        json={"workspace_name": "安全团队", "display_name": "管理员"},
    ).json()
    assert "admin_code" not in payload
    assert "session_token" not in payload
    assert "invite" not in payload


```

Add separate executable tests, using the existing `configured_client()` and direct SQLAlchemy queries, that assert:

- exactly one Workspace;
- exactly one active WorkspaceMember with `role == MemberRole.ADMIN`;
- exactly one active WorkspaceSession;
- audit actions `workspace.created`, `member.owner_created`, `session.created`;
- no WorkspaceAccessCode.
- two separate `TestClient` instances can each create an owner session and read their own workbench context as Admin, while the first receives 404 for the second Workspace;
- monkeypatching `_create_session` to raise after Workspace and Member flush, followed by the router's rollback/cleanup, leaves zero Workspace, WorkspaceMember, WorkspaceSession and AuditLog rows;
- `"  C哥内容团队  "` and `"  小白  "` are stored as trimmed values;
- whitespace-only values return 422 and create no rows.

Update `apps/api/tests/core/test_rate_limit.py` so:

```python
assert (
    category_for_request("POST", "/v1/workspaces/onboard")
    == RateLimitCategory.AUTH
)
```

- [ ] **Step 3: Run RED**

```bash
cd apps/api
.venv/bin/pytest \
  tests/workspace/test_owner_onboarding.py \
  tests/core/test_rate_limit.py -q
```

Expected: fail because `WorkspaceOwnerOnboard`, `/v1/workspaces/onboard` and `create_owner_session` do not exist, and the route is not classified as AUTH.

- [ ] **Step 4: Add strict request schema**

In `apps/api/app/modules/workspace/schemas.py`, add:

```python
from pydantic import field_validator


class WorkspaceOwnerOnboard(BaseModel):
    workspace_name: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("workspace_name", "display_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized
```

Do not coerce non-string values and do not add a role field.

- [ ] **Step 5: Refactor session creation without changing invite behavior**

In `InviteAuthService`, extract the existing session-token creation from `redeem` into a private method with the exact signature `def _create_session(self, member: WorkspaceMember) -> AuthenticatedSession`. Move the current random session token, random CSRF token, expiry, `WorkspaceSession`, `session.created` audit and `WorkspaceContext` construction into that method without changing those statements. `redeem` must continue to call `redeem_member(raw_code, display_name=display_name, client_key=client_key)`, flush, and return `_create_session(member)`. Its current rate-limit, invite validation, role and audit behavior must remain unchanged.

- [ ] **Step 6: Implement atomic owner creation**

Add:

```python
def create_owner_session(
    self,
    *,
    workspace_name: str,
    display_name: str,
) -> AuthenticatedSession:
    workspace = Workspace(name=workspace_name)
    self._session.add(workspace)
    self._session.flush()

    member = WorkspaceMember(
        workspace_id=workspace.id,
        display_name=display_name,
        role=MemberRole.ADMIN,
    )
    self._session.add(member)
    self._session.flush()

    self._session.add_all(
        [
            AuditLog(
                workspace_id=workspace.id,
                member_id=member.id,
                action="workspace.created",
                resource_type="workspace",
                resource_id=workspace.id,
            ),
            AuditLog(
                workspace_id=workspace.id,
                member_id=member.id,
                action="member.owner_created",
                resource_type="workspace_member",
                resource_id=member.id,
            ),
        ]
    )
    return self._create_session(member)
```

Do not call `_issue_code`; the created Workspace must have zero access-code rows.

- [ ] **Step 7: Add the endpoint and share cookie rendering**

Extract a private router helper that sets the existing `session` cookie and renders `SessionCreated`. Use it from both invite login and owner onboarding so cookie flags cannot drift.

Add:

```python
@router.post(
    "/workspaces/onboard",
    response_model=SessionCreated,
    status_code=201,
)
def onboard_workspace_owner(
    data: WorkspaceOwnerOnboard,
    response: Response,
    session: DatabaseSession,
) -> SessionCreated:
    authenticated = InviteAuthService(session).create_owner_session(
        workspace_name=data.workspace_name,
        display_name=data.display_name,
    )
    session.commit()
    return _render_session(response, authenticated)
```

On an unexpected database failure, allow the standard safe 500 contract and dependency cleanup to roll back; do not return exception text.

- [ ] **Step 8: Classify onboarding as AUTH**

Change the first condition of `category_for_request` to include both:

```python
{"/v1/sessions/invite", "/v1/workspaces/onboard"}
```

The existing 10/minute AUTH policy and Redis failure behavior remain authoritative.

- [ ] **Step 9: Run GREEN and regress invitations**

```bash
cd apps/api
.venv/bin/pytest \
  tests/workspace/test_owner_onboarding.py \
  tests/workspace/test_workspace_api.py \
  tests/workspace/test_invites.py \
  tests/workspace/test_permissions.py \
  tests/core/test_rate_limit.py -q
.venv/bin/ruff check app/modules/workspace app/core/rate_limit.py \
  tests/workspace/test_owner_onboarding.py tests/core/test_rate_limit.py
.venv/bin/mypy app
```

Expected: all pass. Verify the old create-workspace-plus-invite test helpers remain compatible.

- [ ] **Step 10: Regenerate and verify OpenAPI**

```bash
cd ../..
pnpm schemas:generate
pnpm schemas:check
```

Confirm `WorkspaceOwnerOnboard` and the typed onboarding operation exist, while `SessionCreated` remains the response.

- [ ] **Step 11: Run full API regression and commit Task 1**

```bash
cd apps/api
.venv/bin/pytest -q
cd ../..
git diff --check
```

Before staging, confirm the only untracked unrelated path is the protected `.superpowers/brainstorm/`.

```bash
git add \
  apps/api/app/modules/workspace/schemas.py \
  apps/api/app/modules/workspace/auth.py \
  apps/api/app/modules/workspace/router.py \
  apps/api/app/core/rate_limit.py \
  apps/api/tests/workspace/test_owner_onboarding.py \
  apps/api/tests/core/test_rate_limit.py \
  packages/shared-schemas/openapi.json \
  packages/shared-schemas/src/schema.ts
git commit -m "feat: onboard initial workspace owners"
```

Pause for acceptance. Do not begin Task 2.

---

### Task 2: Dual entry UI and portable launcher integration

**Files:**
- Modify: `apps/web/src/lib/workspace-api.ts`
- Modify: `apps/web/src/app/enter/page.tsx`
- Modify: `apps/web/src/app/enter/page.test.tsx`
- Modify: `portable/启动运营工具-macOS.command`
- Modify: `portable/启动运营工具-Windows.bat`
- Modify: `portable/使用说明.txt`
- Modify: `apps/api/tests/open_source/test_portable_launchers.py`
- Modify if required by exact archive assertions: `apps/api/tests/open_source/test_portable_builder.py`

**Interfaces:**
- Consumes: Task 1 `POST /v1/workspaces/onboard` and generated `WorkspaceOwnerOnboard`/`SessionCreated` types.
- Produces: `onboardWorkspaceOwner(workspaceName, displayName)`, a dual-path `/enter`, and launchers that only start services and open `/enter`.

- [ ] **Step 1: Read UI and portable test rules**

Read completely:

```text
/Users/baiyan1/.codex/plugins/cache/superpowers-dev/superpowers/6.2.0/skills/test-driven-development/SKILL.md
apps/web/src/app/enter/page.tsx
apps/web/src/app/enter/page.test.tsx
apps/web/src/lib/workspace-api.ts
portable/启动运营工具-macOS.command
portable/启动运营工具-Windows.bat
apps/api/tests/open_source/test_portable_launchers.py
apps/api/tests/open_source/test_portable_builder.py
```

- [ ] **Step 2: Write failing Web tests**

Expand `apps/web/src/app/enter/page.test.tsx` with mocked workspace API calls and user events. Cover:

```tsx
test("shows persistent create-team and join-team paths", () => {
  render(<EnterPage />);
  expect(screen.getByRole("button", { name: "创建团队" })).toBeVisible();
  expect(screen.getByRole("button", { name: "加入团队" })).toBeVisible();
});
```

Add complete Testing Library tests with these exact arrangements and assertions:

- mock `onboardWorkspaceOwner` to resolve `{workspace_id: "workspace-owner", member_id: "member-owner", csrf_token: "csrf-owner"}`; click `创建团队`, fill `团队名称` with `C哥内容团队`, fill `我的名称` with `小白`, submit `创建团队并进入`, and assert the mock was called only with `("C哥内容团队", "小白")`;
- click `加入团队`, fill `邀请码` with `synthetic.invite`, fill `我的名称` with `运营同事`, submit `加入团队`, and assert `enterWorkspace` was called only with `("synthetic.invite", "运营同事")`;
- after either successful response, assert `sessionStorage.getItem("workspace_csrf")` equals the returned CSRF value and `window.location.assign` receives `/workspaces/{workspace_id}`;
- assert the persistent page copy contains both `创建团队不需要邀请码` and `换浏览器或换电脑后，需要另一个管理员邀请码`;
- use a manually controlled pending Promise for owner onboarding, submit once, assert `创建团队并进入` is disabled and a second click makes no second API call, reject with `创建失败，请稍后重试`, then assert the safe message is visible and the button is enabled;
- retain accessibility assertions for associated `团队名称`、`邀请码`、`我的名称` labels and named mode/submit buttons.

- [ ] **Step 3: Write failing launcher-contract tests**

Change `test_portable_launchers.py` so it requires:

```python
def test_launchers_leave_team_creation_to_the_enter_page() -> None:
    for path in (MAC_START, WINDOWS_START):
        text = _text(path)
        assert "/v1/workspaces" not in text
        assert "admin_code" not in text
        assert "bootstrap.json" not in text
        assert "首次登录信息.txt" not in text
        assert "pbcopy" not in text
        assert "Set-Clipboard" not in text
        assert "/enter" in text
```

Update the guide contract to require `创建团队`, `团队名称`, `管理者名称`, `独立邀请码` and the cross-device recovery warning.

- [ ] **Step 4: Run RED**

```bash
pnpm --filter web test:run -- src/app/enter/page.test.tsx
cd apps/api
.venv/bin/pytest tests/open_source/test_portable_launchers.py -q
```

Expected: Web fails because only invite entry exists; launcher tests fail because Task 1 still performs bootstrap.

- [ ] **Step 5: Add typed owner-onboarding client**

In `workspace-api.ts`, use generated types:

```ts
type WorkspaceOwnerOnboard = components["schemas"]["WorkspaceOwnerOnboard"];
type SessionCreated = components["schemas"]["SessionCreated"];

export function onboardWorkspaceOwner(
  workspaceName: string,
  displayName: string,
) {
  const payload: WorkspaceOwnerOnboard = {
    workspace_name: workspaceName,
    display_name: displayName,
  };
  return request<SessionCreated>("/v1/workspaces/onboard", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
```

Do not add custom handwritten response types.

- [ ] **Step 6: Implement the dual-path entry page**

Keep both choices permanently available with a simple local mode:

```ts
type EntryMode = "create" | "join";
```

Requirements:

- default to `create`;
- heading `进入你的运营工作区`;
- mode buttons `创建团队` and `加入团队` with pressed/selected semantics;
- create fields `团队名称` and `我的名称`;
- join fields `邀请码` and `我的名称`;
- create submit label `创建团队并进入`;
- join submit label `加入团队`;
- success for either mode stores only `workspace_csrf` in sessionStorage;
- success navigates to `/workspaces/{workspace_id}`, not member settings;
- no invite code, session token or form payload is persisted or put in the URL;
- visible copy explains that later members use independent codes and a manager changing device also needs an Admin invite;
- preserve one main landmark, keyboard operation, visible focus and 390px single-column layout.

- [ ] **Step 7: Remove launcher-owned workspace bootstrap**

For both start launchers, delete all creation and credential behavior:

- `.local-state` creation used only for bootstrap;
- `bootstrap.json` and temporary file;
- `首次登录信息.txt`;
- `POST /v1/workspaces`;
- JSON parsing via `plutil`/PowerShell;
- `pbcopy`/`Set-Clipboard`;
- any output mentioning initial invite codes.

Retain exactly:

- self-location;
- Docker/Compose checks;
- `.env` create-without-overwrite;
- bounded API and `/enter` health waits;
- project/port/headless overrides;
- `up -d --build`;
- open `/enter` unless `PORTABLE_NO_OPEN=1`;
- non-destructive stop behavior.

The macOS launcher may now remove its `plutil` prerequisite. The Windows launcher still uses built-in PowerShell only for bounded HTTP readiness.

- [ ] **Step 8: Update the usage guide**

State plainly:

- a team manager selects `创建团队`, enters team and personal names, and needs no invite;
- every later member selects `加入团队`, enters their own name and a manager-issued independent invite;
- names are display data, not passwords;
- a manager on a new browser/device needs another Admin invite because there is no account/password recovery system;
- normal stop/restart retains data;
- Mock and Windows `not_run` boundaries remain unchanged.

Remove all instructions referring to `.local-state/首次登录信息.txt` or an initial admin invite generated by the launcher.

- [ ] **Step 9: Run focused GREEN**

```bash
pnpm --filter web test:run -- src/app/enter/page.test.tsx
cd apps/api
.venv/bin/pytest \
  tests/open_source/test_portable_launchers.py \
  tests/open_source/test_portable_builder.py \
  tests/open_source/test_release_security.py -q
cd ../..
pnpm --filter web lint
pnpm --filter web typecheck
pnpm --filter web build
```

Expected: all pass.

- [ ] **Step 10: Rebuild twice and independently verify**

The builder requires a clean committed tree. First commit only after all source tests pass:

```bash
git diff --check
git add \
  apps/web/src/lib/workspace-api.ts \
  apps/web/src/app/enter/page.tsx \
  apps/web/src/app/enter/page.test.tsx \
  portable/启动运营工具-macOS.command \
  portable/启动运营工具-Windows.bat \
  portable/使用说明.txt \
  apps/api/tests/open_source/test_portable_launchers.py \
  apps/api/tests/open_source/test_portable_builder.py
git commit -m "feat: add owner and invite entry paths"
```

Then build from the clean commit twice:

```bash
apps/api/.venv/bin/python scripts/build-portable-release.py \
  --repository . \
  --output-dir /tmp/portable-owner-a \
  --version 0.1.0 \
  --source-date-epoch 1785744000
apps/api/.venv/bin/python scripts/build-portable-release.py \
  --repository . \
  --output-dir /tmp/portable-owner-b \
  --version 0.1.0 \
  --source-date-epoch 1785744000
shasum -a 256 /tmp/portable-owner-a/*.zip /tmp/portable-owner-b/*.zip
apps/api/.venv/bin/python scripts/release-security.py \
  verify-portable-release \
  --path /tmp/portable-owner-a/operations-ai-portable-0.1.0.zip
apps/api/.venv/bin/python scripts/release-security.py \
  verify-portable-release \
  --path /tmp/portable-owner-b/operations-ai-portable-0.1.0.zip
```

Expected:

- both ZIP hashes are identical;
- verifier prints `portable_release=clean`;
- archive contains both platform launchers and updated guide;
- archive contains no `.local-state`, `bootstrap.json`, `首次登录信息.txt`, invite code, Cookie, `.env`, `.git`, `dist`, cache or protected brainstorm path.

- [ ] **Step 11: Run final integrated regression and pause**

```bash
cd apps/api
.venv/bin/pytest -q
cd ../..
pnpm --filter web test:run
pnpm schemas:check
pnpm secret:scan
git diff --check
git status --short
```

Run the secret scan from a tracked-only isolated snapshot if the repository scanner would enumerate the protected untracked brainstorm directory.

Report:

- both task commit SHAs;
- API/Web/portable test totals;
- OpenAPI, Ruff, Mypy, ESLint, TypeScript and build results;
- deterministic ZIP path, size and SHA-256;
- confirmation that initial-manager invite artifacts no longer exist;
- protected directory untouched;
- Windows runtime still `not_run`;
- no real provider/platform/database/volume access.

Do not start the original portable-release Task 3 until the acceptance thread approves both onboarding tasks.
