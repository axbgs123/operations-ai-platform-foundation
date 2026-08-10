# Capture Extension Pairing and Safe Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver and install a macOS Chrome `0.2.0` extension that pairs to the current Web member with a one-time code and completes a user-confirmed screenshot, redaction, upload, Mock recognition, and Web review flow.

**Architecture:** PostgreSQL stores HMAC digests for five-minute one-time pairing codes, while the existing extension token service issues an eight-hour session-only capture token for the already authenticated member. The Web exposes one shared pairing panel from the topbar and import center. The extension uses only the current `activeTab` and declared creator-platform hosts; a content-script overlay owns selection and redaction, the background worker captures the visible tab, and existing capture-task APIs remain the only upload and polling boundary.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, Next.js 16, React 19, TypeScript, Manifest V3, Vite, Vitest, pytest, Playwright.

## Global Constraints

- Pairing codes are eight characters, exclude ambiguous characters, expire after five minutes, and are returned only once.
- Pairing reuses the current Admin or Editor member; it never creates a `WorkspaceMember` and never consumes a member invitation.
- Extension tokens contain only `capture:create`, `capture:upload`, and `capture:read`, expire after eight hours, and remain in `chrome.storage.session` only.
- Viewer, Demo, revoked members, expired codes, reused codes, and cross-workspace access must fail safely.
- Do not add `cookies`, `webRequest`, `tabs`, `<all_urls>`, remote scripts, `eval`, source maps, or persistent screenshot storage.
- The extension captures only the visible current tab after an explicit user action; it does not scroll, publish, bypass login, or automate platform restrictions.
- Web confirmation remains mandatory before formal snapshot creation.
- macOS Chrome local acceptance is in scope. Windows, Edge runtime acceptance, real platform compatibility claims, stores, GitHub Release, and agent computer control are out of scope.
- Do not read, modify, scan, stage, commit, or package the pre-existing `.superpowers/brainstorm/` directory.

---

### Task 1: One-time pairing records and existing-member token issuance

**Files:**
- Create: `apps/api/app/modules/imports/extension_pairing.py`
- Create: `apps/api/migrations/versions/20260810_0035_extension_pairing_codes.py`
- Create: `apps/api/tests/imports/test_extension_pairing_service.py`
- Modify: `apps/api/app/modules/imports/models.py`
- Modify: `apps/api/app/modules/imports/extension_auth.py`
- Modify: `apps/api/app/core/schema_consistency.py`
- Modify: `apps/api/tests/workspace/test_schema_consistency.py`

**Interfaces:**
- Produces: `ExtensionPairingCode` ORM record.
- Produces: `CreatedPairingCode(code: str, expires_at: datetime)`.
- Produces: `ExtensionPairingService.create(workspace_id: UUID, member_id: UUID) -> CreatedPairingCode`.
- Produces: `ExtensionPairingService.redeem(code: str, client_id: str) -> IssuedExtensionToken`.
- Changes: `ExtensionTokenService.lifetime` from 15 minutes to 8 hours without changing the three granted scopes.

- [ ] **Step 1: Write service tests that fail because pairing records and service do not exist**

Create tests for plaintext exclusion, one active code per member, expiry, one-time redemption, simultaneous redemption, existing-member reuse, revoked member rejection, and eight-hour token expiry. The central assertions must include:

```python
created = service.create(workspace_id=workspace.id, member_id=editor.id)
assert len(created.code) == 8
assert created.code not in str(session.scalar(select(ExtensionPairingCode)))

before_members = session.scalar(
    select(func.count()).select_from(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace.id
    )
)
issued = service.redeem(created.code, client_id="operations-capture-extension")
after_members = session.scalar(
    select(func.count()).select_from(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace.id
    )
)
assert issued.member_id == editor.id
assert after_members == before_members
assert issued.expires_at - issued.issued_at == timedelta(hours=8)
```

- [ ] **Step 2: Run the new service test and verify RED**

Run:

```bash
cd apps/api && uv run pytest tests/imports/test_extension_pairing_service.py -q
```

Expected: collection fails because `extension_pairing` and `ExtensionPairingCode` do not exist.

- [ ] **Step 3: Add the ORM record and migration**

Define the record with indexed workspace/member references and a unique digest:

```python
class ExtensionPairingCode(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "extension_pairing_codes"
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    member_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspace_members.id", ondelete="CASCADE")
    )
    code_digest: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
```

Migration `20260810_0035` must revise `20260805_0034`, create the table and three indexes, and drop only that table on downgrade. Add the table to schema consistency requirements.

- [ ] **Step 4: Implement deterministic boundaries and atomic redemption**

Use alphabet `23456789ABCDEFGHJKLMNPQRSTUVWXYZ`. Create the digest with HMAC-SHA256 and `settings.session_signing_secret`; normalize input by uppercasing and removing ASCII spaces/hyphens. Creation revokes the member's unused codes before generating a unique code. Redemption uses `SELECT ... FOR UPDATE`, validates member status, marks `used_at`, calls `ExtensionTokenService.issue`, and flushes within the same transaction.

Expose stable exceptions:

```python
class PairingCodeUnavailable(ValueError): ...
class PairingCodeRateLimited(ValueError): ...
```

The exception must not reveal whether the code was absent, expired, revoked, reused, or bound to a revoked member.

- [ ] **Step 5: Verify GREEN and migration integrity**

Run:

```bash
cd apps/api && uv run pytest tests/imports/test_extension_pairing_service.py tests/workspace/test_schema_consistency.py -q
```

Then run the repository's isolated migration check against a new temporary PostgreSQL schema. Expected head: `20260810_0035`; `alembic check` reports no new upgrade operations.

- [ ] **Step 6: Commit Task 1**

```bash
git add apps/api/app/modules/imports/extension_pairing.py apps/api/app/modules/imports/models.py apps/api/app/modules/imports/extension_auth.py apps/api/app/core/schema_consistency.py apps/api/migrations/versions/20260810_0035_extension_pairing_codes.py apps/api/tests/imports/test_extension_pairing_service.py apps/api/tests/workspace/test_schema_consistency.py
git commit -m "feat: issue one-time extension pairing codes"
```

---

### Task 2: Pairing API, permissions, rate limits, and generated contracts

**Files:**
- Create: `apps/api/tests/imports/test_extension_pairing_api.py`
- Modify: `apps/api/app/modules/imports/extension_router.py`
- Modify: `apps/api/app/core/rate_limit.py`
- Modify: `apps/api/openapi.json`
- Modify: `packages/shared-schemas/src/generated/openapi.ts`

**Interfaces:**
- Produces: `POST /v1/workspaces/{workspace_id}/extension-pairing-codes`.
- Produces: `POST /v1/extension/pair`.
- Produces schemas `ExtensionPairingCodeRead`, `ExtensionPairRequest`, and expanded `ExtensionBindResponse`/`ExtensionBindingRead`.
- Consumes: Task 1 `ExtensionPairingService` and existing Web session permission helpers.

- [ ] **Step 1: Write failing API permission and lifecycle tests**

Cover Admin and Editor success, Viewer/Demo/extension-token rejection, CSRF enforcement, cross-workspace 404, one-time response, old-code invalidation, generic exchange errors, rate limiting, and safe response fields. Assert that member count remains unchanged after pairing.

```python
created = client.post(
    f"/v1/workspaces/{workspace_id}/extension-pairing-codes",
    headers={"X-CSRF-Token": csrf},
)
paired = client.post(
    "/v1/extension/pair",
    headers={"X-Extension-Client": "operations-capture-extension"},
    json={
        "pairing_code": created.json()["pairing_code"],
        "client_id": "operations-capture-extension",
    },
)
assert paired.status_code == 201
assert paired.json()["workspace_name"] == "合成配对工作区"
assert paired.json()["web_origin"] == "http://localhost:3000"
assert paired.json()["member_id"] == editor_member_id
```

- [ ] **Step 2: Run the API test and verify RED**

```bash
cd apps/api && uv run pytest tests/imports/test_extension_pairing_api.py -q
```

Expected: 404 for both new routes.

- [ ] **Step 3: Implement the Web-authenticated creation route**

Require the existing content-write permission used by Admin/Editor and the current `WorkspaceContext`. Return:

```python
class ExtensionPairingCodeRead(BaseModel):
    pairing_code: str
    expires_at: datetime
    workspace_id: UUID
    workspace_name: str
```

Do not return `member_id`, digest, session identifiers, or an extension token from this route.

- [ ] **Step 4: Implement the unauthenticated exchange route**

Validate fixed client headers exactly as `/bind` does. On success return the existing three scopes plus `workspace_name`, `member_display_name`, and `web_origin`. On any invalid pairing condition return `401 {"detail":"pairing code invalid or expired"}`. Keep `/bind` functional for version `0.1.0`, but mark it deprecated in OpenAPI.

- [ ] **Step 5: Add rate-limit classification and secret-safe logs**

Classify `/v1/extension/pair` with authentication limits and fail closed if the Redis limiter is unavailable. Structured logs may contain request ID, stable error code, client ID, workspace/member correlation after successful redemption, and duration; they must not contain the code or token.

- [ ] **Step 6: Regenerate and verify OpenAPI and TypeScript**

Run the repository OpenAPI generation command, run it a second time, and require an empty second diff. Verify generated types expose the new response fields without `pairing_code` appearing in binding reads.

- [ ] **Step 7: Run Task 2 and extension-auth regression tests**

```bash
cd apps/api && uv run pytest tests/imports/test_extension_pairing_api.py tests/imports/test_extension_auth.py tests/imports/test_extension_capture.py -q
```

- [ ] **Step 8: Commit Task 2**

```bash
git add apps/api/app/modules/imports/extension_router.py apps/api/app/core/rate_limit.py apps/api/tests/imports/test_extension_pairing_api.py apps/api/openapi.json packages/shared-schemas/src/generated/openapi.ts
git commit -m "feat: expose secure extension pairing api"
```

---

### Task 3: Shared Web pairing panel and discoverable entries

**Files:**
- Create: `apps/web/src/lib/extension-pairing-api.ts`
- Create: `apps/web/src/components/extension/extension-pairing-panel.tsx`
- Create: `apps/web/src/components/extension/extension-pairing-panel.test.tsx`
- Modify: `apps/web/src/components/workbench/workspace-topbar.tsx`
- Modify: `apps/web/src/components/workbench/workspace-shell.test.tsx`
- Modify: `apps/web/src/components/imports/import-center.tsx`
- Modify: `apps/web/src/components/imports/import-center.test.tsx`

**Interfaces:**
- Produces: `createExtensionPairingCode(workspaceId: string, csrfToken: string): Promise<ExtensionPairingCodeRead>`.
- Produces: `ExtensionPairingPanel({workspaceId, role, triggerLabel})`.
- Consumes: Task 2 generated API schema.

- [ ] **Step 1: Write failing component tests**

Test that Admin/Editor see “连接扩展” in the topbar and import method, Viewer sees only explanatory read-only text, code is rendered once with a five-minute countdown, regenerate replaces the displayed code, copy uses the Clipboard API, and close clears plaintext from React state.

```tsx
await user.click(screen.getByRole("button", { name: "连接扩展" }));
await user.click(screen.getByRole("button", { name: "生成连接码" }));
expect(await screen.findByText("ABCD2345")).toBeVisible();
expect(screen.getByText(/5 分钟内有效/)).toBeVisible();
```

- [ ] **Step 2: Run focused Web tests and verify RED**

```bash
pnpm --filter web test:run -- src/components/extension/extension-pairing-panel.test.tsx src/components/workbench/workspace-shell.test.tsx src/components/imports/import-center.test.tsx
```

Expected: module-not-found for the pairing panel.

- [ ] **Step 3: Implement the generated-type API client**

Use `NEXT_PUBLIC_API_URL`, `credentials: "include"`, `X-CSRF-Token`, and the generated response type. Map 401/403/404/429/5xx to safe Chinese messages without echoing response bodies.

- [ ] **Step 4: Implement the accessible pairing dialog**

The dialog must include:

- “连接浏览器扩展” title and a short three-step explanation.
- Code rendered with `aria-live="polite"` only after generation.
- Countdown derived from server `expires_at`, not a client-created five-minute value.
- “复制连接码”“重新生成”“关闭” actions.
- A fixed local-server hint `http://127.0.0.1:51201` labeled as the current portable default, not a universal production address.
- Focus return, Escape close, and plaintext state clearing on close/unmount.

- [ ] **Step 5: Add both entries with role-correct visibility**

Place the compact topbar trigger before Help. In the Extension import method replace the old passive binding text with the same panel trigger. Do not duplicate API calls or pairing state across pages.

- [ ] **Step 6: Verify GREEN, accessibility, and production build**

```bash
pnpm --filter web test:run -- src/components/extension/extension-pairing-panel.test.tsx src/components/workbench/workspace-shell.test.tsx src/components/imports/import-center.test.tsx
pnpm --filter web lint
pnpm --filter web typecheck
pnpm --filter web build
```

- [ ] **Step 7: Commit Task 3**

```bash
git add apps/web/src/lib/extension-pairing-api.ts apps/web/src/components/extension/extension-pairing-panel.tsx apps/web/src/components/extension/extension-pairing-panel.test.tsx apps/web/src/components/workbench/workspace-topbar.tsx apps/web/src/components/workbench/workspace-shell.test.tsx apps/web/src/components/imports/import-center.tsx apps/web/src/components/imports/import-center.test.tsx
git commit -m "feat: make extension pairing discoverable"
```

---

### Task 4: Version 0.2 Popup pairing and page readiness

**Files:**
- Create: `apps/extension/tests/popup-pairing.test.ts`
- Modify: `apps/extension/package.json`
- Modify: `apps/extension/src/build-metadata.ts`
- Modify: `apps/extension/src/auth/client.ts`
- Modify: `apps/extension/src/auth/storage.ts`
- Modify: `apps/extension/src/popup/index.html`
- Modify: `apps/extension/src/popup/main.ts`
- Modify: `apps/extension/src/content/page-adapters/base.ts`
- Modify: `apps/extension/src/content/page-adapters/douyin.ts`
- Modify: `apps/extension/src/content/page-adapters/xiaohongshu.ts`
- Modify: `apps/extension/src/content/page-support.ts`
- Modify: `apps/extension/tests/auth.test.ts`
- Modify: `apps/extension/tests/page-detection.test.ts`
- Modify: `apps/extension/tests/manifest.test.ts`

**Interfaces:**
- Produces: `pairExtension({serverOrigin, pairingCode, clientId}, dependencies)`.
- Expands stored `ExtensionBinding` with `workspaceName`, `memberDisplayName`, and `webOrigin`.
- Produces: `detectSupportedPage(url: string)` based only on declared creator-platform hostname/path.
- Produces Popup messages `{type:"GET_PAGE_STATUS"}` and `{type:"START_SAFE_CAPTURE"}`.

- [ ] **Step 1: Write failing Popup and auth tests**

Test default local API, hidden advanced server input, code clearing after both success and failure, safe binding disclosure, three Popup states, expired binding degradation, unsupported-page explanation, and start-button visibility only when paired and supported.

- [ ] **Step 2: Run extension tests and verify RED**

```bash
pnpm --filter extension test -- tests/popup-pairing.test.ts tests/auth.test.ts tests/page-detection.test.ts tests/manifest.test.ts
```

Expected: missing `pairExtension` and old invite form assertions fail.

- [ ] **Step 3: Replace invite exchange with pairing exchange**

POST to `/v1/extension/pair`, retain dynamic host permission approval, and store only:

```ts
type ExtensionBinding = {
  serverOrigin: string;
  webOrigin: string;
  workspaceId: string;
  workspaceName: string;
  memberDisplayName: string;
  accessToken: string;
  expiresAt: string;
  providerMode: "mock" | "qianwen" | "unavailable";
  region: string | null;
};
```

Clear the code input in a `finally` block. Never write it to local or session storage.

- [ ] **Step 4: Rebuild Popup state and copy**

Use simple light styling bundled locally. The unpaired form contains code plus “高级设置”; paired state contains destination disclosure, processing mode, expiry, current page status, “开始安全采集”, and “解绑”. Do not expose a raw token or workspace/member UUID.

- [ ] **Step 5: Replace fixture-only production detection**

Production support returns a stable platform and page version from the URL alone:

```ts
const SUPPORTED = {
  douyin: {
    hostname: "creator.douyin.com",
    pathPrefix: "/creator-micro/content/manage",
    pageVersion: "douyin-visible-tab-v1",
  },
  xiaohongshu: {
    hostname: "creator.xiaohongshu.com",
    pathPrefix: "/publish/publish-manage",
    pageVersion: "xiaohongshu-visible-tab-v1",
  },
} as const;
```

Retain fixture metadata only in fixture test helpers. It must not be required by runtime detection.

- [ ] **Step 6: Keep the permission boundary unchanged**

Assert the Manifest still has exactly `activeTab`, `scripting`, `storage`; declared host permissions remain the two creator URL patterns; no `cookies`, `tabs`, `webRequest`, `<all_urls>` or remote code appears.

- [ ] **Step 7: Verify GREEN and commit Task 4**

```bash
pnpm --filter extension test
pnpm --filter extension lint
pnpm --filter extension typecheck
pnpm --filter extension build:chrome
```

```bash
git add apps/extension/package.json apps/extension/src/build-metadata.ts apps/extension/src/auth/client.ts apps/extension/src/auth/storage.ts apps/extension/src/popup/index.html apps/extension/src/popup/main.ts apps/extension/src/content/page-adapters/base.ts apps/extension/src/content/page-adapters/douyin.ts apps/extension/src/content/page-adapters/xiaohongshu.ts apps/extension/src/content/page-support.ts apps/extension/tests/popup-pairing.test.ts apps/extension/tests/auth.test.ts apps/extension/tests/page-detection.test.ts apps/extension/tests/manifest.test.ts
git commit -m "feat: pair capture extension with current members"
```

---

### Task 5: User-selected capture, redaction, upload, and review handoff

**Files:**
- Create: `apps/extension/src/content/capture-overlay.ts`
- Create: `apps/extension/src/content/image-processing.ts`
- Create: `apps/extension/src/runtime/messages.ts`
- Create: `apps/extension/tests/capture-overlay.test.ts`
- Create: `apps/extension/tests/runtime-wiring.test.ts`
- Modify: `apps/extension/src/background.ts`
- Modify: `apps/extension/src/content.ts`
- Modify: `apps/extension/src/content/overlay.ts`
- Modify: `apps/extension/src/content/redaction.ts`
- Modify: `apps/extension/src/capture/upload.ts`
- Modify: `apps/extension/src/capture/task-status.ts`
- Modify: `apps/extension/src/popup/main.ts`
- Modify: `apps/extension/tests/safe-mode.test.ts`
- Modify: `apps/extension/tests/upload.test.ts`
- Modify: `apps/extension/tests/fallback.test.ts`

**Interfaces:**
- Produces typed messages `GET_PAGE_STATUS`, `START_SAFE_CAPTURE`, `CAPTURE_VISIBLE_TAB`, `OPEN_REVIEW`.
- Produces `cropVisibleTab(dataUrl: string, selection: Rect, viewport: ViewportMetrics): Promise<string>`.
- Produces `applyRedactions(dataUrl: string, redactions: Rect[]): Promise<string>` that outputs a controlled PNG data URL.
- Produces `CaptureOverlay.mount(options)` and `CaptureOverlay.destroy()`.
- Consumes: Task 4 binding and runtime URL detection; existing `uploadPreview` and `pollCaptureTask`.

- [ ] **Step 1: Write failing runtime and overlay tests**

Cover explicit-start requirement, drag normalization, minimum 40×40 selection, device-pixel-ratio crop, overlay hiding during capture, redaction addition/removal, no upload before final confirmation, cancellation cleanup, URL change failure, 401 re-pair, idempotency, polling completion, timeout, and safe review URL composition.

The central state assertion is:

```ts
expect(flow.state).toBe("selecting");
flow.confirmSelection({x: 20, y: 30, width: 500, height: 300});
expect(captureVisibleTab).toHaveBeenCalledTimes(1);
expect(flow.state).toBe("previewing");
flow.addRedaction({x: 40, y: 50, width: 120, height: 32});
await flow.confirmUpload();
expect(upload).toHaveBeenCalledTimes(1);
```

- [ ] **Step 2: Run focused extension tests and verify RED**

```bash
pnpm --filter extension test -- tests/capture-overlay.test.ts tests/runtime-wiring.test.ts tests/safe-mode.test.ts tests/upload.test.ts
```

Expected: missing overlay, image-processing, and message modules.

- [ ] **Step 3: Implement the typed message boundary**

Validate every message at runtime before use. Background accepts `CAPTURE_VISIBLE_TAB` only from the active supported tab after a Popup/content-script initiated flow. It calls `chrome.tabs.captureVisibleTab(sender.tab.windowId, {format:"png"})`; `activeTab` remains the authorization boundary.

- [ ] **Step 4: Implement selection and controlled image processing**

The overlay uses pointer events and keyboard Escape. Normalize reversed drags, clamp to viewport, reject selections under 40×40 CSS pixels, and hide all extension UI for one animation frame before capture. Decode into a canvas, crop with `devicePixelRatio`, draw opaque rectangles, and export PNG. Reject decode failure, zero dimensions, or output above the existing upload byte limit.

- [ ] **Step 5: Implement preview and disclosure UI**

Preview must show platform, server, selected size, redaction count, Mock/real processing disclosure, “重新选择”“添加遮挡”“取消”“确认上传”. The user can delete each redaction. Upload is impossible before selection capture and final preview confirmation.

- [ ] **Step 6: Connect upload, polling, and Web review**

Build the idempotency key from a random per-capture UUID held only in memory. Poll with existing capped backoff. On success open exactly:

```ts
new URL(task.review_url, binding.webOrigin).toString()
```

Validate that the result origin equals `binding.webOrigin` and pathname begins with `/workspaces/${binding.workspaceId}/imports`. Render the validated URL as a normal user-clicked `<a target="_blank" rel="noopener noreferrer">到运营工具确认</a>` inside the content overlay; do not call `chrome.tabs.create` and do not add the `tabs` permission.

- [ ] **Step 7: Verify GREEN, full extension regression, and artifact security**

```bash
pnpm --filter extension test
pnpm --filter extension lint
pnpm --filter extension typecheck
pnpm --filter extension build:chrome
pnpm --filter extension build:edge
```

Scan both build outputs for remote script URLs, `eval`, source maps, tokens, pairing codes, screenshots, unexpected permissions, and platform data.

- [ ] **Step 8: Commit Task 5**

```bash
git add apps/extension/src/content/capture-overlay.ts apps/extension/src/content/image-processing.ts apps/extension/src/runtime/messages.ts apps/extension/src/background.ts apps/extension/src/content.ts apps/extension/src/content/overlay.ts apps/extension/src/content/redaction.ts apps/extension/src/capture/upload.ts apps/extension/src/capture/task-status.ts apps/extension/src/popup/main.ts apps/extension/tests/capture-overlay.test.ts apps/extension/tests/runtime-wiring.test.ts apps/extension/tests/safe-mode.test.ts apps/extension/tests/upload.test.ts apps/extension/tests/fallback.test.ts
git commit -m "feat: complete preview-first extension capture"
```

---

### Task 6: Cross-product acceptance, deterministic package, and Chrome installation

**Files:**
- Create: `tests/e2e/extension-pairing-safe-capture.spec.ts`
- Create: `docs/acceptance/extension-0.2.0-macos-chrome.md`
- Modify: `tests/e2e/playwright.extension.config.ts`
- Modify: `docs/open-source/extension-installation.md`
- Modify: `docs/open-source/extension-privacy.md`
- Modify: `docs/open-source/extension-validation-status.md`
- Modify: `apps/extension/scripts/package-extension.mjs`
- Modify: `scripts/verify-portable-release.sh`

**Interfaces:**
- Produces deterministic `operations-capture-extension-chrome-0.2.0.zip` and Edge equivalent.
- Produces a local acceptance record with no pairing code, token, cookie, CSRF value, screenshot body, title, account name, or OCR text.
- Consumes all prior tasks.

- [ ] **Step 1: Write the failing isolated E2E acceptance**

The fixture must use a temporary PostgreSQL schema, temporary object prefix, Mock provider, two independent browser contexts, and a synthetic supported creator page. It must assert:

1. Admin creates a pairing code.
2. Extension context redeems it without changing member count.
3. Reuse fails.
4. User selects and redacts a synthetic visible region.
5. Upload creates a workspace-scoped capture task.
6. Mock recognition succeeds.
7. Extension cannot confirm.
8. Editor Web session chooses an account and confirms.
9. Screenshot staging object is cleaned according to the existing lifecycle.

- [ ] **Step 2: Run E2E and verify RED**

Run the dedicated extension Playwright configuration. Expected failure: `0.2.0` packed-extension path or complete flow fixture is unavailable.

- [ ] **Step 3: Update documentation and validation boundaries**

Document the exact local server `http://127.0.0.1:51201`, Web pairing steps, eight-hour session token, safe capture controls, review requirement, uninstall/解绑 behavior, and errors. State separately:

- macOS Chrome unpacked package: verified after Step 7.
- macOS/Windows Edge: not run.
- Windows Chrome: not run.
- Real Douyin/Xiaohongshu pages: not run.

- [ ] **Step 4: Build deterministic packages twice**

Run the package command twice from the same clean commit and fixed source-date epoch. Require identical file lists and SHA-256 hashes for repeated builds. Chrome and Edge business content must be identical except declared browser metadata.

- [ ] **Step 5: Run full automated verification**

Run sequentially to avoid resource-starvation timeouts:

```bash
cd apps/api && uv run pytest -q
pnpm --filter web test:run
pnpm --filter extension test
pnpm --filter web lint
pnpm --filter web typecheck
pnpm --filter web build
pnpm --filter extension lint
pnpm --filter extension typecheck
pnpm --filter extension package
bash scripts/secret-scan.sh
git diff --check
```

Also run OpenAPI drift, generated TypeScript drift, isolated migration to `20260810_0035`, `alembic check`, schema consistency, Docker Compose config, extension manifest permission scan, and the dedicated E2E.

- [ ] **Step 6: Request final code review and resolve every Critical/Important issue**

Review must explicitly inspect pairing enumeration, member reuse, HMAC/plaintext boundaries, token lifetime/revocation, message sender validation, image memory lifetime, review URL validation, workspace/platform isolation, Manifest permissions, and release contents.

- [ ] **Step 7: Install the verified unpacked extension in the user's macOS Chrome**

Use Chrome's `chrome://extensions` UI:

1. Preserve all unrelated extensions.
2. Inspect any older “运营数据采集助手” unpacked build: use Reload when its source path is the same `apps/extension/release/unpacked` directory; remove only that extension when its source path differs.
3. Enable Developer mode if disabled.
4. Load `apps/extension/release/unpacked`.
5. Confirm name `运营数据采集助手`, version `0.2.0`, and only the expected permissions.
6. Pinning is optional; do not reorder or remove unrelated pinned extensions.

- [ ] **Step 8: Perform local macOS Chrome acceptance without real platform data**

Use a synthetic creator-page fixture and a temporary test workspace/member/account. Complete pairing, selection, redaction, upload, Mock processing, and Web review. Remove only the synthetic acceptance records and temporary resources created by this step; preserve the user's existing local workspace and Docker volumes.

- [ ] **Step 9: Commit Task 6 and pause**

```bash
git add tests/e2e/extension-pairing-safe-capture.spec.ts tests/e2e/playwright.extension.config.ts docs/acceptance/extension-0.2.0-macos-chrome.md docs/open-source/extension-installation.md docs/open-source/extension-privacy.md docs/open-source/extension-validation-status.md apps/extension/scripts/package-extension.mjs scripts/verify-portable-release.sh
git commit -m "test: accept capture extension 0.2.0"
```

Do not push, merge, create a GitHub Release, start Windows validation, or claim real platform compatibility.
