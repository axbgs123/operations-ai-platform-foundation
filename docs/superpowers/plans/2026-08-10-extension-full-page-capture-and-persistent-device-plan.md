# Extension Full-Page Capture and Persistent Device Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a shortcut-driven, preview-first full-page capture flow with optional redaction and a device connection that survives browser restarts without storing a permanent bearer token.

**Architecture:** Keep device identity and renewal separate from capture. A non-exportable P-256 device key in extension-owned IndexedDB signs one-time server challenges; short-lived access tokens remain in `chrome.storage.session`. Full-page capture uses an explicitly armed Service Worker session, rate-limited visible-tab slices, a content-side scrolling driver, a bounded stitcher, and the existing user-confirmed upload/review boundary.

**Tech Stack:** FastAPI, SQLAlchemy 2, PostgreSQL, Redis, Alembic, Pydantic, WebCrypto, IndexedDB, Chrome Manifest V3, TypeScript, Vite, React/Next.js, Vitest, Pytest, Playwright.

## Global Constraints

- Default shortcut: macOS `Command+Shift+8`; Windows/Linux `Ctrl+Shift+8`; show the actual registered shortcut or a collision warning in the Popup, workbench pairing panel, and docs.
- Do not add `<all_urls>`, `cookies`, `tabs`, `webRequest`, or `debugger` permissions.
- Only an explicit extension action or Commands API shortcut may start capture.
- Full-page capture stops at the first of: bottom stable twice, 30 slices, or 20 seconds; `captureVisibleTab` calls must not exceed 2 per second.
- Restore the original scroll position on success, cancellation, and failure.
- Stitched output limits: 40,000,000 pixels, 32,000-pixel longest edge, 10 MiB encoded payload.
- Redaction is optional and off by default; upload always requires an explicit final confirmation.
- “Persistent connection” ends on explicit unlink, admin revocation, member removal, workspace deletion, browser data/key loss, or security revocation.
- The pairing code remains valid for 5 minutes; only the post-pair device relationship is persistent.
- Never persist a permanent bearer token. Access tokens remain session-only and expire after 8 hours.
- Content scripts must not read `chrome.storage.session`; Service Worker responses use strict sender, active-tab, URL, platform, version, signature, and armed-session checks.
- Existing workspace/platform isolation, cross-workspace 404 behavior, admin-only device governance, Mock boundaries, and preview-before-confirm rules remain authoritative.
- Add new Alembic migrations; never edit historical migrations.
- Never access real creator pages or paid providers in automated tests.

---

### Task 1: Persistent Device Domain and Cryptographic Challenge Service

**Files:**
- Modify: `apps/api/app/modules/imports/models.py`
- Create: `apps/api/app/modules/imports/extension_devices.py`
- Create: `apps/api/migrations/versions/20260810_0036_extension_device_bindings.py`
- Modify: `apps/api/app/core/schema_consistency.py`
- Test: `apps/api/tests/imports/test_extension_devices.py`
- Test: `apps/api/tests/workspace/test_migrations.py`

**Interfaces:**
- Produces: `DevicePublicKey`, `ExtensionDeviceIdentity`, `ExtensionDeviceService.register_device(...)`, `ExtensionDeviceService.issue_challenge(...)`, `ExtensionDeviceService.renew_session(...)`, `ExtensionDeviceService.revoke_device(...)`.
- Produces: `ExtensionDeviceBinding` rows and nullable `ExtensionToken.device_id` binding; existing pre-0.3 tokens remain readable until expiry.
- Consumes: existing `ExtensionTokenService`, workspace member status, Redis client, UTC clock, and exact `operations-capture-extension` client ID.

- [ ] **Step 1: Write failing domain and migration tests**

```python
def test_device_challenge_is_single_use_and_renews_a_short_token(session, redis):
    private_key, public_jwk = p256_fixture()
    device = service.register_device(
        workspace_id=workspace.id,
        member_id=admin.id,
        device_id=UUID("00000000-0000-0000-0000-000000000301"),
        public_key_jwk=public_jwk,
        extension_version="0.3.0",
        label="Chrome on macOS",
    )
    challenge = service.issue_challenge(device_id=device.id)
    signature = sign_raw_p256(private_key, challenge.signing_payload)
    renewed = service.renew_session(
        device_id=device.id,
        challenge_id=challenge.id,
        signature=signature,
    )
    assert renewed.expires_at - renewed.issued_at == timedelta(hours=8)
    with pytest.raises(DeviceChallengeUnavailable):
        service.renew_session(device_id=device.id, challenge_id=challenge.id, signature=signature)
```

Also assert malformed JWKs, duplicate device IDs, wrong signatures, expired challenges, revoked devices, removed members, cross-workspace devices, and concurrent challenge consumption fail closed. Migration tests must require `extension_device_bindings`, its unique indexes, `extension_tokens.device_id`, and head `20260810_0036`.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `cd apps/api && uv run pytest tests/imports/test_extension_devices.py tests/workspace/test_migrations.py -q`

Expected: FAIL because the model, service, and migration do not exist.

- [ ] **Step 3: Implement the minimal device service**

```python
@dataclass(frozen=True)
class DeviceChallenge:
    id: UUID
    device_id: UUID
    expires_at: datetime
    signing_payload: bytes

class ExtensionDeviceService:
    challenge_lifetime = timedelta(minutes=2)

    def register_device(
        self, *, workspace_id: UUID, member_id: UUID, device_id: UUID,
        public_key_jwk: dict[str, str], extension_version: str, label: str,
    ) -> ExtensionDeviceIdentity: ...

    def issue_challenge(self, *, device_id: UUID) -> DeviceChallenge: ...

    def renew_session(
        self, *, device_id: UUID, challenge_id: UUID, signature: str,
    ) -> IssuedExtensionToken: ...

    def revoke_device(
        self, *, workspace_id: UUID, device_id: UUID, revoked_by: UUID,
    ) -> None: ...
```

Store only the validated P-256 public JWK and its SHA-256 fingerprint. Store challenge nonce material in Redis under a random, device-bound key with TTL and consume it atomically with Lua. Convert WebCrypto’s 64-byte raw ECDSA signature into DER only inside the verifier. Authentication of a device-bound access token must re-check device/member/workspace active state on every request.

- [ ] **Step 4: Run domain, migration, and imports regression tests**

Run: `cd apps/api && uv run pytest tests/imports/test_extension_devices.py tests/imports/test_extension_auth.py tests/imports/test_extension_pairing_service.py tests/workspace/test_migrations.py -q`

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add apps/api/app/modules/imports/models.py \
  apps/api/app/modules/imports/extension_devices.py \
  apps/api/app/core/schema_consistency.py \
  apps/api/migrations/versions/20260810_0036_extension_device_bindings.py \
  apps/api/tests/imports/test_extension_devices.py \
  apps/api/tests/workspace/test_migrations.py
git commit -m "feat: add persistent extension device identities"
```

### Task 2: Pairing, Renewal, and Admin Device APIs

**Files:**
- Modify: `apps/api/app/modules/imports/extension_router.py`
- Modify: `apps/api/app/modules/imports/extension_pairing.py`
- Modify: `apps/api/app/modules/imports/extension_auth.py`
- Modify: `apps/api/app/core/rate_limit.py`
- Test: `apps/api/tests/imports/test_extension_pairing_api.py`
- Test: `apps/api/tests/imports/test_extension_auth.py`
- Test: `apps/api/tests/imports/test_extension_device_api.py`
- Modify: `apps/api/openapi.json`
- Modify: `apps/web/src/generated/api.ts`

**Interfaces:**
- Consumes: Task 1 `ExtensionDeviceService`.
- Produces: `POST /v1/extension/session/challenge`, `POST /v1/extension/session/renew`, `GET /v1/workspaces/{workspace_id}/extension-devices`, and `DELETE /v1/workspaces/{workspace_id}/extension-devices/{device_id}`.
- Changes: `POST /v1/extension/pair` requires `device_id`, `device_public_key_jwk`, `device_label`, and `extension_version`, and returns `device_id` with the existing short token.

- [ ] **Step 1: Write failing API contract and authorization tests**

```python
def test_admin_can_revoke_device_and_existing_token_stops_working(client, admin_headers):
    paired = pair_real_device(client, admin_headers)
    response = client.delete(
        f"/v1/workspaces/{paired.workspace_id}/extension-devices/{paired.device_id}",
        headers=admin_headers,
    )
    assert response.status_code == 204
    assert extension_read(client, paired.access_token).status_code == 401
```

Cover strict schemas, generic 401 for unknown/replayed challenge, rate limits, idempotent pairing retry, editor/viewer denial, cross-workspace 404, member removal, device list redaction, extension-token inability to list/revoke devices, and OpenAPI fields that never expose public-key bodies or token hashes.

- [ ] **Step 2: Run tests and confirm RED**

Run: `cd apps/api && uv run pytest tests/imports/test_extension_pairing_api.py tests/imports/test_extension_auth.py tests/imports/test_extension_device_api.py -q`

Expected: FAIL because the renewal and admin routes do not exist.

- [ ] **Step 3: Add strict request/response contracts and routes**

```python
class ExtensionSessionChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: UUID
    client_id: Literal["operations-capture-extension"]

class ExtensionSessionRenewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: UUID
    challenge_id: UUID
    signature: Annotated[str, StringConstraints(min_length=86, max_length=88)]
```

All pairing/renewal failures return stable safe codes without device-existence disclosure. Device list responses expose only ID, label, browser/version, created/last-used timestamps, status, and revoked time. Regenerate OpenAPI and TypeScript using repository scripts.

- [ ] **Step 4: Run API, OpenAPI, migration, Ruff, and Mypy checks**

Run: `cd apps/api && uv run pytest tests/imports -q && uv run ruff check app tests && uv run mypy app`

Run: `bash scripts/check-openapi-drift.sh && bash scripts/check-schema-consistency.sh`

Expected: PASS with head `20260810_0036` and no drift.

- [ ] **Step 5: Commit Task 2**

```bash
git add apps/api/app/modules/imports apps/api/app/core/rate_limit.py \
  apps/api/tests/imports apps/api/openapi.json apps/web/src/generated/api.ts
git commit -m "feat: renew and govern extension device sessions"
```

### Task 3: Non-Exportable Device Key and Automatic Session Renewal

**Files:**
- Create: `apps/extension/src/auth/device-key-store.ts`
- Create: `apps/extension/src/auth/device-registration-store.ts`
- Create: `apps/extension/src/auth/session-renewal.ts`
- Modify: `apps/extension/src/auth/client.ts`
- Modify: `apps/extension/src/auth/storage.ts`
- Modify: `apps/extension/src/background.ts`
- Modify: `apps/extension/src/popup/main.ts`
- Test: `apps/extension/tests/device-session.test.ts`
- Modify: `tests/e2e/extension-pairing-safe-capture.spec.ts`

**Interfaces:**
- Consumes: Task 2 pairing and renewal endpoints.
- Produces: `DeviceKeyStore.getOrCreate()`, `DeviceRegistrationStore`, and `SessionManager.ensureFreshBinding(minRemainingMs?: number)`.
- Produces: a persistent, non-secret registration record in `chrome.storage.local`; the non-exportable private key stays in extension-owned IndexedDB and access tokens stay in `chrome.storage.session`.

- [ ] **Step 1: Write failing WebCrypto, restart, and revocation tests**

```ts
it("renews after browser restart without persisting a bearer token", async () => {
  const device = await keyStore.getOrCreate();
  expect(await crypto.subtle.exportKey("jwk", device.privateKey)).rejects.toThrow();
  await sessionStore.clear();
  const binding = await manager.ensureFreshBinding();
  expect(binding.accessToken).toBe("renewed-short-token");
  expect(localStorageWrites).not.toContainEqual(expect.objectContaining({accessToken: expect.anything()}));
});
```

Cover missing IndexedDB key, mismatched device ID, invalid challenge, replay, network timeout, revoked/removed-device 401, session token near expiry, concurrent renewal deduplication, unlink clearing session/registration/key, and service-worker restart.

- [ ] **Step 2: Run extension tests and confirm RED**

Run: `pnpm --filter extension test -- tests/device-session.test.ts`

Expected: FAIL because the stores and manager do not exist.

- [ ] **Step 3: Implement the device key and renewal manager**

```ts
export type DeviceSigner = {
  deviceId: string;
  publicJwk: JsonWebKey;
  sign(payload: Uint8Array): Promise<string>;
};

export interface SessionManager {
  ensureFreshBinding(minRemainingMs?: number): Promise<ExtensionBinding>;
  unlink(): Promise<void>;
}
```

Generate `ECDSA/P-256` with `extractable: false` for the private key; export only the public key. Store `serverOrigin`, `webOrigin`, `workspaceId`, `deviceId`, and display metadata locally, never a token or pairing code. Renew only when the session token is missing or has less than 30 minutes remaining. Serialize concurrent renewal with one in-memory promise.

- [ ] **Step 4: Run extension, E2E pairing, lint, typecheck, and builds**

Run: `pnpm --filter extension test && pnpm --filter extension lint && pnpm --filter extension typecheck`

Run: `pnpm --filter extension build:chrome && pnpm --filter extension build:edge`

Expected: PASS; Chrome/Edge business files remain identical.

- [ ] **Step 5: Commit Task 3**

```bash
git add apps/extension/src/auth apps/extension/src/background.ts \
  apps/extension/src/popup/main.ts apps/extension/tests/device-session.test.ts \
  tests/e2e/extension-pairing-safe-capture.spec.ts
git commit -m "feat: persist extension connection with device keys"
```

### Task 4: Bounded Scroll Capture Driver and Stitcher

**Files:**
- Create: `apps/extension/src/capture/scroll-driver.ts`
- Create: `apps/extension/src/capture/stitcher.ts`
- Create: `apps/extension/src/capture/full-page-types.ts`
- Modify: `apps/extension/src/runtime/messages.ts`
- Modify: `apps/extension/src/background.ts`
- Test: `apps/extension/tests/scroll-capture.test.ts`
- Test: `apps/extension/tests/stitcher.test.ts`
- Test: `apps/extension/tests/runtime-wiring.test.ts`

**Interfaces:**
- Produces: `ScrollCaptureDriver.capture(options): Promise<FullPageCaptureResult>`.
- Produces: `stitchSlices(slices, limits): Promise<StitchedCapture>`.
- Produces: multi-slice runtime messages bound to `captureSessionId`, monotonically increasing `sequence`, platform/page version/signature, exact URL, viewport, DPR, and scroll position.

- [ ] **Step 1: Write failing bounded-scroll and stitching tests**

```ts
it("stops after 30 slices and always restores the original scroll position", async () => {
  const result = await driver.capture({maxSlices: 30, timeoutMs: 20_000});
  expect(result.slices).toHaveLength(30);
  expect(result.complete).toBe(false);
  expect(scrollTo).toHaveBeenLastCalledWith({top: 420, behavior: "instant"});
});
```

Cover bottom stable twice, lazy-load height growth, 20-second timeout, cancellation, visibility/pagehide/blur, layout/DPR/URL/signature drift, 500ms minimum screenshot spacing, ordered sequence, overlap crop, uncertain sticky regions, 40M pixels, 32k edge, 10MiB payload, canvas failure, and partial-result disclosure.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `pnpm --filter extension test -- tests/scroll-capture.test.ts tests/stitcher.test.ts tests/runtime-wiring.test.ts`

Expected: FAIL because full-page contracts do not exist.

- [ ] **Step 3: Implement pure driver/stitcher and fenced background sessions**

```ts
export type FullPageCaptureResult = {
  slices: CaptureSlice[];
  complete: boolean;
  stopReason: "bottom" | "slice-limit" | "time-limit";
  originalScrollY: number;
};

export async function stitchSlices(
  slices: readonly CaptureSlice[],
  limits: {maxPixels: 40_000_000; maxEdge: 32_000; maxBytes: 10 * 1024 * 1024},
): Promise<StitchedCapture> { ... }
```

The Service Worker owns the armed multi-slice session and rejects stale/out-of-order/cross-tab calls. The content script owns scrolling and restores the page in `finally`. Do not hide or mutate creator-page elements to remove sticky headers; only remove overlap proven by slice metadata/pixel checks.

- [ ] **Step 4: Run extension regression and production builds**

Run: `pnpm --filter extension test && pnpm --filter extension lint && pnpm --filter extension typecheck && pnpm --filter extension build:chrome && pnpm --filter extension build:edge`

Expected: PASS; no new Manifest permission.

- [ ] **Step 5: Commit Task 4**

```bash
git add apps/extension/src/capture apps/extension/src/runtime/messages.ts \
  apps/extension/src/background.ts apps/extension/tests
git commit -m "feat: capture bounded full-page screenshot slices"
```

### Task 5: Shortcut, Full-Page Preview, and Optional Redaction UX

**Files:**
- Modify: `apps/extension/manifest.json`
- Modify: `apps/extension/src/background.ts`
- Modify: `apps/extension/src/content.ts`
- Modify: `apps/extension/src/content/capture-overlay.ts`
- Modify: `apps/extension/src/popup/index.html`
- Modify: `apps/extension/src/popup/main.ts`
- Test: `apps/extension/tests/manifest.test.ts`
- Test: `apps/extension/tests/capture-overlay.test.ts`
- Test: `apps/extension/tests/popup-pairing.test.ts`
- Test: `apps/extension/tests/runtime-wiring.test.ts`

**Interfaces:**
- Consumes: Task 3 `SessionManager` and Task 4 driver/stitcher.
- Produces: Manifest command `capture-full-page` and one unified `startCapture("full-page" | "visible" | "region")` coordinator.
- Keeps: existing confirmed upload, polling, 401 re-pairing, safe review link, and workspace/platform isolation.

- [ ] **Step 1: Write failing shortcut and UX tests**

```ts
it("uses the documented shortcut and starts the same full-page coordinator", async () => {
  expect(manifest.commands["capture-full-page"].suggested_key).toEqual({
    default: "Ctrl+Shift+8",
    mac: "Command+Shift+8",
  });
  await commandListener("capture-full-page", supportedTab);
  expect(startCapture).toHaveBeenCalledWith("full-page", supportedTab);
});
```

Assert Popup displays the actual assigned shortcut or collision warning, primary action is “自动采集整页”, visible/region modes are under “更多采集方式”, preview reports completeness/slices/size, redaction defaults off, turning it off with existing masks requires confirmation, and no upload occurs before “确认上传”.

- [ ] **Step 2: Run tests and confirm RED**

Run: `pnpm --filter extension test -- tests/manifest.test.ts tests/capture-overlay.test.ts tests/popup-pairing.test.ts tests/runtime-wiring.test.ts`

Expected: FAIL because the command and full-page UX are absent.

- [ ] **Step 3: Wire the command and preview-first UX**

```ts
export type CaptureMode = "full-page" | "visible" | "region";

export interface CaptureCoordinator {
  startCapture(mode: CaptureMode, tab: SupportedTab): Promise<void>;
  cancel(reason: string): Promise<void>;
}
```

Register `chrome.commands.onCommand`, use the command-provided tab as the explicit activeTab gesture, and route Popup/command through the same coordinator. Keep redaction controls unmounted until the user enables the switch. Upload metadata must include `capture_mode`, `complete`, `stop_reason`, and `slice_count`, but never page正文 or unredacted duplicate bytes.

- [ ] **Step 4: Run extension tests, lint, typecheck, builds, and permission scans**

Run: `pnpm --filter extension test && pnpm --filter extension lint && pnpm --filter extension typecheck`

Run: `pnpm --filter extension build:chrome && pnpm --filter extension build:edge && bash scripts/scan-secrets.sh`

Expected: PASS; the only named permissions remain `activeTab`, `scripting`, and `storage`.

- [ ] **Step 5: Commit Task 5**

```bash
git add apps/extension/manifest.json apps/extension/src apps/extension/tests
git commit -m "feat: add shortcut-driven full-page capture preview"
```

### Task 6: Device Management UI and Operator-Facing Documentation

**Files:**
- Create: `apps/web/src/lib/extension-device-api.ts`
- Create: `apps/web/src/components/extension/extension-device-list.tsx`
- Create: `apps/web/src/components/extension/extension-device-list.test.tsx`
- Modify: `apps/web/src/components/extension/extension-pairing-panel.tsx`
- Modify: `apps/web/src/components/extension/extension-pairing-panel.test.tsx`
- Modify: `apps/web/src/app/workspaces/[workspaceId]/settings/members/page.tsx`
- Modify: `docs/open-source/extension-installation.md`
- Modify: `docs/open-source/extension-privacy.md`
- Modify: `docs/open-source/extension-validation-status.md`

**Interfaces:**
- Consumes: Task 2 device list/revoke APIs and Task 5 shortcut contract.
- Produces: Admin device list and revoke action; Editor/Viewer see only safe connection guidance and cannot revoke.

- [ ] **Step 1: Write failing UI and API-client tests**

```tsx
it("shows the actual shortcut and lets only admins revoke a device", async () => {
  render(<ExtensionDeviceList workspaceId="workspace-1" role="admin" />);
  expect(await screen.findByText("Command + Shift + 8")).toBeVisible();
  await user.click(screen.getByRole("button", {name: "撤销此设备"}));
  expect(revokeExtensionDevice).toHaveBeenCalledWith("workspace-1", "device-1", "csrf");
});
```

Cover safe fields, no public key/token/fingerprint output, pending/error/retry, revocation confirmation, Viewer/Editor no action, cross-workspace 404 messaging, pairing code still 5 minutes, and persistent-connection explanation.

- [ ] **Step 2: Run Web tests and confirm RED**

Run: `pnpm --filter web test -- extension-device-list extension-pairing-panel`

Expected: FAIL because device management UI does not exist.

- [ ] **Step 3: Implement UI and documentation**

```ts
export async function listExtensionDevices(workspaceId: string): Promise<ExtensionDeviceRead[]>;
export async function revokeExtensionDevice(
  workspaceId: string,
  deviceId: string,
  csrfToken: string,
): Promise<void>;
```

Use operator language: “保持连接，直到你或管理员解除”。Explain shortcut customization, bounded/partial page capture, optional redaction default-off, preview-before-upload, device-key loss, and real-platform compatibility limits.

- [ ] **Step 4: Run Web regression, lint, typecheck, and production build**

Run: `pnpm --filter web test && pnpm --filter web lint && pnpm --filter web typecheck && pnpm --filter web build`

Expected: PASS.

- [ ] **Step 5: Commit Task 6**

```bash
git add apps/web/src/lib/extension-device-api.ts apps/web/src/components/extension \
  'apps/web/src/app/workspaces/[workspaceId]/settings/members/page.tsx' \
  docs/open-source/extension-installation.md docs/open-source/extension-privacy.md \
  docs/open-source/extension-validation-status.md
git commit -m "feat: explain and govern persistent extension devices"
```

### Task 7: Isolated Acceptance, Deterministic Package, and macOS Chrome Handoff

**Files:**
- Modify: `tests/e2e/extension-pairing-safe-capture.spec.ts`
- Modify: `tests/e2e/playwright.extension.config.ts`
- Create: `tests/e2e/fixtures/long-creator-page.html`
- Modify: `apps/extension/scripts/package-extension.mjs`
- Modify: `apps/extension/tests/manifest.test.ts`
- Create: `docs/acceptance/extension-0.3.0-macos-chrome.md`
- Modify: `scripts/verify-portable-release.sh`

**Interfaces:**
- Consumes: Tasks 1–6.
- Produces: deterministic Chrome/Edge 0.3.0 packages, truthful acceptance evidence, and a user-installable unpacked directory.

- [ ] **Step 1: Write failing end-to-end acceptance assertions**

```ts
test("persists a device and captures a bounded synthetic long page", async ({page}) => {
  await pairThroughRealPopup();
  await simulateBrowserRestartWithoutSessionStorage();
  await expect(await renewThroughDeviceKey()).toMatchObject({provider_mode: "mock"});
  await triggerCaptureCommand();
  await expect(preview).toContainText("遮挡敏感信息：关");
  await expect(preview).toContainText("采集 6 屏");
  await confirmUploadThroughWeb();
  await expect(stagingObject()).resolves.toBeNull();
});
```

The isolated E2E must use a real unpacked extension context, real Popup pairing, real Service Worker/content-script messages, random schema/Redis/object prefix, Mock Provider, and a routed synthetic creator page. If Playwright cannot produce a real toolbar shortcut gesture or `captureVisibleTab`, mark only that exact segment as component-tested and keep it for manual Chrome acceptance; do not emulate it and claim a full real chain.

- [ ] **Step 2: Run acceptance and confirm RED**

Run: `pnpm exec playwright test -c tests/e2e/playwright.extension.config.ts`

Expected: FAIL until persistent renewal, full-page preview, and package version 0.3.0 are wired.

- [ ] **Step 3: Complete deterministic packaging and evidence**

Build twice with `SOURCE_DATE_EPOCH=1785744000`; require identical file lists and SHA-256 for Chrome/Edge business content. Verify no source maps, remote scripts, `eval`, secrets, screenshots, tokens, IndexedDB files, or test data enter the package. Add acceptance fields for shortcut assignment, device renewal, full-page completeness, redaction default, cleanup, and explicit `not_run` boundaries.

- [ ] **Step 4: Run full repository validation**

Run: `cd apps/api && uv run pytest -q && uv run ruff check app tests && uv run mypy app`

Run: `pnpm --filter web test && pnpm --filter extension test && pnpm --filter web lint && pnpm --filter extension lint && pnpm --filter web typecheck && pnpm --filter extension typecheck`

Run: `bash scripts/check-openapi-drift.sh && bash scripts/check-schema-consistency.sh && bash scripts/scan-secrets.sh`

Run: `pnpm exec playwright test -c tests/e2e/playwright.extension.config.ts`

Expected: all PASS; temporary schema, Redis, browser profile, objects, containers, and volumes are removed.

- [ ] **Step 5: Perform controller-owned macOS Chrome acceptance**

Reload `apps/extension/release/unpacked` without removing unrelated extensions. Confirm name, version `0.3.0`, exact permissions, displayed shortcut, persistent reconnection after browser restart, default-off redaction, manual confirmation, and fallback modes. Test a real creator page only after explicit user approval; otherwise keep real platform compatibility `not_run`.

- [ ] **Step 6: Commit Task 7**

```bash
git add tests/e2e apps/extension/scripts/package-extension.mjs \
  apps/extension/tests/manifest.test.ts docs/acceptance/extension-0.3.0-macos-chrome.md \
  scripts/verify-portable-release.sh
git commit -m "test: accept persistent full-page extension capture"
```
